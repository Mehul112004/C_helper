"""
Unit tests for the StrategyRunner.
Tests validate signal default population, exception safety, and historical scan behavior.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal
from app.core.strategy_runner import StrategyRunner


# ---------- Helpers ----------

def _make_candle(close=100.0, open_=99.0, high=101.0, low=98.0,
                 volume=1000.0, time_offset_hours=0):
    return Candle(
        open_time=datetime(2025, 1, 1) + timedelta(hours=time_offset_hours),
        open=open_, high=high, low=low, close=close, volume=volume,
    )


def _make_candle_list(n=50, base_close=100.0):
    return [
        _make_candle(
            close=base_close + i * 0.01,
            open_=base_close + i * 0.01 - 0.5,
            high=base_close + i * 0.01 + 1.0,
            low=base_close + i * 0.01 - 1.0,
            volume=1000.0,
            time_offset_hours=i,
        )
        for i in range(n)
    ]


class AlwaysSignalStrategy(BaseStrategy):
    """Test strategy that always returns a LONG signal."""
    name = "Always Signal"
    timeframes = ["1h", "4h"]

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction="LONG",
            confidence=0.70,
            # Intentionally leave entry, SL, TP as None to test defaults
        )


class NeverSignalStrategy(BaseStrategy):
    """Test strategy that never signals."""
    name = "Never Signal"
    timeframes = ["1h", "4h"]

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        return None


class CrashingStrategy(BaseStrategy):
    """Test strategy that raises an exception."""
    name = "Crasher"
    timeframes = ["1h", "4h"]

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        raise RuntimeError("Intentional crash for testing")


class LowConfidenceStrategy(BaseStrategy):
    """Test strategy that returns signals with low confidence."""
    name = "Low Confidence"
    timeframes = ["1h"]
    min_confidence = 0.7

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction="LONG",
            confidence=0.40,  # Below min_confidence
            entry=candles[-1].close,
        )


class TestRunSingleScan:
    """Tests for StrategyRunner.run_single_scan()."""

    def test_populates_defaults(self):
        """SL/TP/entry are populated when strategy returns None for them."""
        strategy = AlwaysSignalStrategy()
        candles = _make_candle_list(50)
        indicators = Indicators(atr_14=2.0)

        signal = StrategyRunner.run_single_scan(
            strategy, "BTCUSDT", "4h", candles, indicators, []
        )

        assert signal is not None
        assert signal.entry is not None
        assert signal.sl is not None
        assert signal.tp1 is not None
        assert signal.tp2 is not None

    def test_catches_exceptions(self):
        """A crashing strategy returns None, doesn't kill the runner."""
        strategy = CrashingStrategy()
        candles = _make_candle_list(50)
        indicators = Indicators(atr_14=2.0)

        signal = StrategyRunner.run_single_scan(
            strategy, "BTCUSDT", "4h", candles, indicators, []
        )

        assert signal is None  # Should not raise

    def test_none_signal_passes_through(self):
        """A strategy returning None results in None from runner."""
        strategy = NeverSignalStrategy()
        candles = _make_candle_list(50)
        indicators = Indicators()

        signal = StrategyRunner.run_single_scan(
            strategy, "BTCUSDT", "4h", candles, indicators, []
        )

        assert signal is None

    def test_min_confidence_filters(self):
        """Signals below strategy's min_confidence are filtered out."""
        strategy = LowConfidenceStrategy()
        candles = _make_candle_list(50)
        indicators = Indicators(atr_14=2.0)

        signal = StrategyRunner.run_single_scan(
            strategy, "BTCUSDT", "1h", candles, indicators, []
        )

        assert signal is None  # 0.40 < min_confidence 0.70

    def test_min_confidence_override(self):
        """min_confidence_override from session overrides strategy's threshold."""
        strategy = LowConfidenceStrategy()
        candles = _make_candle_list(50)
        indicators = Indicators(atr_14=2.0)

        # Override to 0.3 — signal at 0.40 should now pass
        signal = StrategyRunner.run_single_scan(
            strategy, "BTCUSDT", "1h", candles, indicators, [],
            min_confidence_override=0.3,
        )

        assert signal is not None
        assert signal.confidence == 0.40

    def test_sl_tp_values_correct(self):
        """Default SL/TP should follow ATR-based formulas."""
        strategy = AlwaysSignalStrategy()
        candle = _make_candle(close=100.0)
        candles = _make_candle_list(49) + [candle]
        indicators = Indicators(atr_14=10.0)

        signal = StrategyRunner.run_single_scan(
            strategy, "BTCUSDT", "4h", candles, indicators, []
        )

        assert signal is not None
        assert signal.entry == 100.0
        assert signal.sl == 85.0    # 100 - 1.5 * 10
        assert signal.tp1 == 120.0  # 100 + 2.0 * 10
        assert signal.tp2 == 135.0  # 100 + 3.5 * 10


class TestScanHistorical:
    """Tests for StrategyRunner.scan_historical()."""

    def _make_df(self, n=100):
        """Create a DataFrame suitable for scan_historical."""
        dates = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)]
        np.random.seed(42)
        closes = 100.0 + np.cumsum(np.random.uniform(-0.5, 0.5, n))

        return pd.DataFrame({
            'open_time': dates,
            'open': closes - 0.5,
            'high': closes + 1.0,
            'low': closes - 1.0,
            'close': closes,
            'volume': np.random.uniform(800, 1200, n),
        })

    def _make_indicator_series(self, n=100):
        """Create a mock indicator series dict."""
        return {
            'ema_9': [{'value': 100.0 + i * 0.01} for i in range(n)],
            'ema_21': [{'value': 99.0 + i * 0.01} for i in range(n)],
            'ema_50': [{'value': 97.0 + i * 0.01} for i in range(n)],
            'ema_200': [{'value': 93.0 + i * 0.01} for i in range(n)],
            'rsi_14': [{'value': 50.0} for _ in range(n)],
            'macd_line': [{'value': 0.5} for _ in range(n)],
            'macd_signal': [{'value': 0.4} for _ in range(n)],
            'macd_histogram': [{'value': 0.1} for _ in range(n)],
            'bb_upper': [{'value': 105.0} for _ in range(n)],
            'bb_middle': [{'value': 100.0} for _ in range(n)],
            'bb_lower': [{'value': 95.0} for _ in range(n)],
            'bb_width': [{'value': 0.10} for _ in range(n)],
            'atr_14': [{'value': 2.0} for _ in range(n)],
            'volume_ma_20': [{'value': 1000.0} for _ in range(n)],
        }

    def test_produces_signals(self):
        """Running AlwaysSignal over historical data produces signals."""
        df = self._make_df(100)
        series = self._make_indicator_series(100)
        strategies = [AlwaysSignalStrategy()]

        signals = StrategyRunner.scan_historical(
            strategies, "BTCUSDT", "4h", df, series, []
        )

        # AlwaysSignal fires on every bar after idx 50
        assert len(signals) > 0

    def test_respects_timeframe_filter(self):
        """Strategy with timeframes=["4h"] is not run on "1D" data."""
        df = self._make_df(100)
        series = self._make_indicator_series(100)

        # AlwaysSignal has timeframes ["1h", "4h"]
        strategies = [AlwaysSignalStrategy()]

        signals = StrategyRunner.scan_historical(
            strategies, "BTCUSDT", "1D", df, series, []  # "1D" not in strategy
        )

        assert len(signals) == 0

    def test_timestamps_match_candles(self):
        """Signal timestamps should match the candle bar's open_time."""
        df = self._make_df(100)
        series = self._make_indicator_series(100)
        strategies = [AlwaysSignalStrategy()]

        signals = StrategyRunner.scan_historical(
            strategies, "BTCUSDT", "4h", df, series, []
        )

        for signal in signals:
            assert signal.timestamp is not None
            # Should be a datetime, not the default utcnow
            assert signal.timestamp.year == 2025

    def test_exception_safety_in_scan(self):
        """A crashing strategy doesn't prevent other strategies from running."""
        df = self._make_df(100)
        series = self._make_indicator_series(100)
        strategies = [CrashingStrategy(), AlwaysSignalStrategy()]

        signals = StrategyRunner.scan_historical(
            strategies, "BTCUSDT", "4h", df, series, []
        )

        # AlwaysSignal should still produce signals despite Crasher
        assert len(signals) > 0
