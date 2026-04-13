"""
Unit tests for the core data classes and BaseStrategy contract.
Tests verify Candle, Indicators, SetupSignal, and BaseStrategy behavior.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from app.core.base_strategy import Candle, Indicators, SetupSignal, BaseStrategy


class TestCandle:
    """Tests for the Candle dataclass."""

    def test_candle_creation(self):
        """Basic candle creation with all fields."""
        candle = Candle(
            open_time=datetime(2025, 1, 1),
            open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0
        )
        assert candle.open == 100.0
        assert candle.close == 105.0

    def test_candle_from_db_row(self):
        """Candle.from_db_row() correctly parses a dict."""
        row = {
            'open_time': '2025-01-01T00:00:00',
            'open': 100.0, 'high': 110.0, 'low': 90.0,
            'close': 105.0, 'volume': 1000.0,
        }
        candle = Candle.from_db_row(row)
        assert candle.open == 100.0
        assert candle.close == 105.0
        assert isinstance(candle.open_time, datetime)

    def test_candle_from_df_row(self):
        """Candle.from_df_row() correctly parses a pandas Series."""
        row = pd.Series({
            'open_time': pd.Timestamp('2025-01-01'),
            'open': 100.0, 'high': 110.0, 'low': 90.0,
            'close': 105.0, 'volume': 1000.0,
        })
        candle = Candle.from_df_row(row)
        assert candle.open == 100.0
        assert isinstance(candle.open_time, datetime)

    def test_candle_is_frozen(self):
        """Candle should be immutable (frozen=True)."""
        candle = Candle(
            open_time=datetime(2025, 1, 1),
            open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0
        )
        with pytest.raises(AttributeError):
            candle.close = 200.0

    def test_candle_body_size(self):
        """body_size should be |close - open|."""
        candle = Candle(
            open_time=datetime(2025, 1, 1),
            open=100.0, high=110.0, low=90.0, close=108.0, volume=1000.0
        )
        assert candle.body_size == 8.0

    def test_candle_range_size(self):
        """range_size should be high - low."""
        candle = Candle(
            open_time=datetime(2025, 1, 1),
            open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0
        )
        assert candle.range_size == 20.0

    def test_candle_upper_wick(self):
        """upper_wick = high - max(open, close)."""
        candle = Candle(
            open_time=datetime(2025, 1, 1),
            open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0
        )
        assert candle.upper_wick == 5.0  # 110 - max(100, 105) = 5

    def test_candle_lower_wick(self):
        """lower_wick = min(open, close) - low."""
        candle = Candle(
            open_time=datetime(2025, 1, 1),
            open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0
        )
        assert candle.lower_wick == 10.0  # min(100, 105) - 90 = 10

    def test_candle_bullish(self):
        """Bullish candle: close > open."""
        candle = Candle(
            open_time=datetime(2025, 1, 1),
            open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0
        )
        assert candle.is_bullish is True
        assert candle.is_bearish is False

    def test_candle_bearish(self):
        """Bearish candle: close < open."""
        candle = Candle(
            open_time=datetime(2025, 1, 1),
            open=105.0, high=110.0, low=90.0, close=100.0, volume=1000.0
        )
        assert candle.is_bullish is False
        assert candle.is_bearish is True


class TestIndicators:
    """Tests for the Indicators dataclass."""

    def test_indicators_defaults(self):
        """All indicator fields should default to None."""
        ind = Indicators()
        assert ind.ema_9 is None
        assert ind.rsi_14 is None
        assert ind.bb_width_history == []

    def test_indicators_from_series(self):
        """Indicators.from_series() correctly extracts current + prev values."""
        series = {
            'ema_9': [{'value': 100.0}, {'value': 101.0}, {'value': 102.0}],
            'ema_21': [{'value': 99.0}, {'value': 100.0}, {'value': 101.0}],
            'ema_50': [{'value': 95.0}, {'value': 96.0}, {'value': 97.0}],
            'ema_200': [{'value': 90.0}, {'value': 91.0}, {'value': 92.0}],
            'rsi_14': [{'value': 45.0}, {'value': 50.0}, {'value': 55.0}],
            'macd_line': [{'value': 0.5}, {'value': 0.6}, {'value': 0.7}],
            'macd_signal': [{'value': 0.4}, {'value': 0.5}, {'value': 0.6}],
            'macd_histogram': [{'value': 0.1}, {'value': 0.1}, {'value': 0.1}],
            'bb_upper': [{'value': 105.0}, {'value': 106.0}, {'value': 107.0}],
            'bb_middle': [{'value': 100.0}, {'value': 101.0}, {'value': 102.0}],
            'bb_lower': [{'value': 95.0}, {'value': 96.0}, {'value': 97.0}],
            'bb_width': [{'value': 0.10}, {'value': 0.09}, {'value': 0.08}],
            'atr_14': [{'value': 2.0}, {'value': 2.1}, {'value': 2.2}],
            'volume_ma_20': [{'value': 1000.0}, {'value': 1100.0}, {'value': 1200.0}],
        }

        ind = Indicators.from_series(series, idx=2)

        # Current bar values (idx=2)
        assert ind.ema_9 == 102.0
        assert ind.ema_21 == 101.0
        assert ind.rsi_14 == 55.0
        assert ind.atr_14 == 2.2

        # Previous bar values (idx=1)
        assert ind.prev_ema_9 == 101.0
        assert ind.prev_ema_21 == 100.0
        assert ind.prev_rsi_14 == 50.0

        # BB width history
        assert len(ind.bb_width_history) == 3
        assert ind.bb_width_history == [0.10, 0.09, 0.08]

    def test_indicators_from_series_boundary(self):
        """Indicators.from_series() handles idx=0 gracefully (no prev values)."""
        series = {
            'ema_9': [{'value': 100.0}],
            'ema_21': [{'value': 99.0}],
        }
        ind = Indicators.from_series(series, idx=0)
        assert ind.ema_9 == 100.0
        assert ind.prev_ema_9 is None  # No previous bar at idx=0

    def test_indicators_bb_width_history_max_20(self):
        """BB width history should contain at most 20 values."""
        bb_values = [{'value': float(i) * 0.01} for i in range(50)]
        series = {'bb_width': bb_values}

        ind = Indicators.from_series(series, idx=49)
        assert len(ind.bb_width_history) == 20


class TestSetupSignal:
    """Tests for the SetupSignal dataclass."""

    def test_valid_long_signal(self):
        """Can create a valid LONG signal."""
        signal = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="LONG", confidence=0.75
        )
        assert signal.direction == "LONG"
        assert signal.confidence == 0.75

    def test_valid_short_signal(self):
        """Can create a valid SHORT signal."""
        signal = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="SHORT", confidence=0.60
        )
        assert signal.direction == "SHORT"

    def test_invalid_direction(self):
        """Should raise ValueError for invalid direction."""
        with pytest.raises(ValueError, match="direction must be"):
            SetupSignal(
                strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
                direction="UP", confidence=0.75
            )

    def test_invalid_confidence_too_high(self):
        """Should raise ValueError for confidence > 1.0."""
        with pytest.raises(ValueError, match="confidence must be"):
            SetupSignal(
                strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
                direction="LONG", confidence=1.5
            )

    def test_invalid_confidence_negative(self):
        """Should raise ValueError for confidence < 0.0."""
        with pytest.raises(ValueError, match="confidence must be"):
            SetupSignal(
                strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
                direction="LONG", confidence=-0.1
            )

    def test_signal_to_dict(self):
        """to_dict() should produce a JSON-serializable dictionary."""
        signal = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="LONG", confidence=0.75, entry=67000.0,
            sl=66000.0, tp1=68000.0, tp2=69000.0,
            notes="Test notes"
        )
        d = signal.to_dict()
        assert d['direction'] == "LONG"
        assert d['entry'] == 67000.0
        assert d['notes'] == "Test notes"

    def test_signal_boundary_confidence(self):
        """Confidence at exact boundaries (0.0 and 1.0) should be valid."""
        signal_zero = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="LONG", confidence=0.0
        )
        signal_one = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="LONG", confidence=1.0
        )
        assert signal_zero.confidence == 0.0
        assert signal_one.confidence == 1.0


class TestBaseStrategy:
    """Tests for the BaseStrategy abstract class."""

    def test_cannot_instantiate_directly(self):
        """BaseStrategy cannot be instantiated directly (abstract)."""
        with pytest.raises(TypeError):
            BaseStrategy()

    def test_subclass_must_implement_scan(self):
        """A subclass without scan() cannot be instantiated."""
        class IncompleteStrategy(BaseStrategy):
            name = "Incomplete"

        with pytest.raises(TypeError):
            IncompleteStrategy()

    def test_valid_subclass(self):
        """A properly implemented subclass can be instantiated."""
        class TestStrategy(BaseStrategy):
            name = "Test Strategy"
            timeframes = ["1h"]

            def scan(self, symbol, timeframe, candles, indicators, sr_zones):
                return None

        strategy = TestStrategy()
        assert strategy.name == "Test Strategy"

    def test_default_sl_long(self):
        """Default SL for LONG: entry - 1.5 × ATR."""
        class TestStrategy(BaseStrategy):
            name = "Test"
            def scan(self, symbol, timeframe, candles, indicators, sr_zones):
                return None

        strategy = TestStrategy()
        signal = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="LONG", confidence=0.75, entry=100.0
        )
        candle = Candle(datetime(2025, 1, 1), 99.0, 101.0, 98.0, 100.0, 1000.0)
        sl = strategy.calculate_sl(signal, [candle], atr=10.0)
        assert sl == 85.0  # 100 - 1.5 * 10

    def test_default_sl_short(self):
        """Default SL for SHORT: entry + 1.5 × ATR."""
        class TestStrategy(BaseStrategy):
            name = "Test"
            def scan(self, symbol, timeframe, candles, indicators, sr_zones):
                return None

        strategy = TestStrategy()
        signal = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="SHORT", confidence=0.75, entry=100.0
        )
        candle = Candle(datetime(2025, 1, 1), 101.0, 102.0, 99.0, 100.0, 1000.0)
        sl = strategy.calculate_sl(signal, [candle], atr=10.0)
        assert sl == 115.0  # 100 + 1.5 * 10

    def test_default_tp_long(self):
        """Default TP for LONG: TP1 = 2×ATR, TP2 = 3.5×ATR from entry."""
        class TestStrategy(BaseStrategy):
            name = "Test"
            def scan(self, symbol, timeframe, candles, indicators, sr_zones):
                return None

        strategy = TestStrategy()
        signal = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="LONG", confidence=0.75, entry=100.0
        )
        candle = Candle(datetime(2025, 1, 1), 99.0, 101.0, 98.0, 100.0, 1000.0)
        tp1, tp2 = strategy.calculate_tp(signal, [candle], atr=10.0)
        assert tp1 == 120.0  # 100 + 2 * 10
        assert tp2 == 135.0  # 100 + 3.5 * 10

    def test_default_tp_short(self):
        """Default TP for SHORT: TP1 = entry - 2×ATR, TP2 = entry - 3.5×ATR."""
        class TestStrategy(BaseStrategy):
            name = "Test"
            def scan(self, symbol, timeframe, candles, indicators, sr_zones):
                return None

        strategy = TestStrategy()
        signal = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="SHORT", confidence=0.75, entry=100.0
        )
        candle = Candle(datetime(2025, 1, 1), 101.0, 102.0, 99.0, 100.0, 1000.0)
        tp1, tp2 = strategy.calculate_tp(signal, [candle], atr=10.0)
        assert tp1 == 80.0   # 100 - 2 * 10
        assert tp2 == 65.0   # 100 - 3.5 * 10

    def test_should_confirm_with_llm_default(self):
        """Default should_confirm_with_llm returns True."""
        class TestStrategy(BaseStrategy):
            name = "Test"
            def scan(self, symbol, timeframe, candles, indicators, sr_zones):
                return None

        strategy = TestStrategy()
        signal = SetupSignal(
            strategy_name="Test", symbol="BTCUSDT", timeframe="4h",
            direction="LONG", confidence=0.75
        )
        assert strategy.should_confirm_with_llm(signal) is True

    def test_min_confidence_default(self):
        """Default min_confidence should be 0.5."""
        class TestStrategy(BaseStrategy):
            name = "Test"
            def scan(self, symbol, timeframe, candles, indicators, sr_zones):
                return None

        strategy = TestStrategy()
        assert strategy.min_confidence == 0.5

    def test_min_confidence_custom(self):
        """Strategies can set a custom min_confidence."""
        class HighConfStrategy(BaseStrategy):
            name = "HighConf"
            min_confidence = 0.8
            def scan(self, symbol, timeframe, candles, indicators, sr_zones):
                return None

        strategy = HighConfStrategy()
        assert strategy.min_confidence == 0.8
