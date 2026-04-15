"""
Unit tests for all 6 built-in strategies.
Each strategy is tested with synthetic indicator/candle data designed to trigger
specific conditions. No database required — all data is fabricated in the test.
"""

import pytest
from datetime import datetime, timedelta
from app.core.base_strategy import Candle, Indicators, SetupSignal


# ---------- Helper factories ----------

def _make_candle(
    close=100.0, open_=99.0, high=101.0, low=98.0,
    volume=1000.0, time_offset_hours=0
):
    """Create a single Candle with controllable values."""
    return Candle(
        open_time=datetime(2025, 1, 1) + timedelta(hours=time_offset_hours),
        open=open_, high=high, low=low, close=close, volume=volume,
    )


def _make_candle_list(n=50, base_close=100.0):
    """Create a list of n dummy candles for padding strategy windows."""
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


def _make_indicators(**overrides):
    """Create an Indicators instance with sensible defaults and overrides."""
    defaults = dict(
        ema_9=100.0, ema_21=99.0, ema_50=97.0, ema_200=93.0,
        rsi_14=50.0, macd_line=0.5, macd_signal=0.4,
        macd_histogram=0.1, bb_upper=105.0, bb_middle=100.0,
        bb_lower=95.0, bb_width=0.10, atr_14=2.0,
        volume_ma_20=1000.0,
        prev_ema_9=99.0, prev_ema_21=100.0,
        prev_macd_line=0.3, prev_macd_signal=0.4,
        prev_macd_histogram=-0.1, prev_rsi_14=50.0,
        prev_bb_upper=104.0, prev_bb_lower=96.0,
        prev_bb_width=0.08,
        bb_width_history=[0.08] * 20,
        rsi_14_history=[50.0] * 5,
    )
    defaults.update(overrides)
    return Indicators(**defaults)


# =============================================================================
# EMA Crossover Tests
# =============================================================================

class TestEMACrossover:
    """Tests for the EMA Crossover strategy."""

    @pytest.fixture
    def strategy(self):
        from app.strategies.ema_crossover import EMACrossoverStrategy
        return EMACrossoverStrategy()

    def test_bullish_crossover(self, strategy):
        """EMA9 crosses above EMA21 with close > EMA50 → LONG signal."""
        candles = _make_candle_list(49) + [_make_candle(close=101.0, volume=1200.0)]
        indicators = _make_indicators(
            ema_9=101.0, ema_21=100.5,       # Current: EMA9 > EMA21
            prev_ema_9=99.0, prev_ema_21=100.0,  # Previous: EMA9 < EMA21 (cross!)
            ema_50=97.0,                        # close > EMA50 ✓
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "LONG"
        assert signal.confidence >= 0.60

    def test_bearish_crossover(self, strategy):
        """EMA9 crosses below EMA21 with close < EMA50 → SHORT signal."""
        candles = _make_candle_list(49) + [_make_candle(close=95.0, volume=1200.0)]
        indicators = _make_indicators(
            ema_9=94.5, ema_21=95.0,         # Current: EMA9 < EMA21
            prev_ema_9=96.0, prev_ema_21=95.0, # Previous: EMA9 > EMA21 (cross!)
            ema_50=97.0,                        # close < EMA50 ✓
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "SHORT"

    def test_no_crossover(self, strategy):
        """EMAs parallel, no cross → None."""
        candles = _make_candle_list(50)
        indicators = _make_indicators(
            ema_9=101.0, ema_21=100.0,
            prev_ema_9=100.5, prev_ema_21=99.5,  # Both above: no cross
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None

    def test_counter_trend_filtered(self, strategy):
        """Bullish cross but close < EMA50 (counter-trend) → None."""
        candles = _make_candle_list(49) + [_make_candle(close=95.0)]
        indicators = _make_indicators(
            ema_9=96.0, ema_21=95.5,
            prev_ema_9=94.0, prev_ema_21=95.0,  # Bullish cross
            ema_50=97.0,                          # But close < EMA50!
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None

    def test_confidence_with_volume(self, strategy):
        """Crossover + high volume → higher confidence."""
        candles = _make_candle_list(49) + [_make_candle(close=101.0, volume=1500.0)]
        indicators = _make_indicators(
            ema_9=101.0, ema_21=100.5,
            prev_ema_9=99.0, prev_ema_21=100.0,
            ema_50=97.0, ema_200=90.0,
            volume_ma_20=1000.0,
            rsi_14=50.0,
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        # Base 0.60 + vol 0.10 + EMA200 0.10 + RSI mid 0.05 = 0.85
        assert signal.confidence >= 0.80

    def test_missing_prev_ema_returns_none(self, strategy):
        """Missing previous EMA values → None."""
        candles = _make_candle_list(50)
        indicators = _make_indicators(prev_ema_9=None, prev_ema_21=None)
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None


# =============================================================================
# RSI Reversal Tests
# =============================================================================

class TestRSIReversal:
    """Tests for the RSI Reversal strategy."""

    @pytest.fixture
    def strategy(self):
        from app.strategies.rsi_reversal import RSIReversalStrategy
        return RSIReversalStrategy()

    def test_oversold_reversal(self, strategy):
        """RSI crosses above 35 from oversold → LONG signal."""
        candles = _make_candle_list(49) + [_make_candle(close=101.0)]
        indicators = _make_indicators(
            rsi_14=36.0,           # Now above 35
            prev_rsi_14=34.0,      # Was below 35
            ema_50=97.0,           # Close > EMA50 ✓
            ema_200=90.0,          # Close > EMA200 ✓
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "LONG"

    def test_overbought_reversal(self, strategy):
        """RSI crosses below 65 from overbought → SHORT signal."""
        candles = _make_candle_list(49) + [_make_candle(close=95.0)]
        indicators = _make_indicators(
            rsi_14=64.0,           # Now below 65
            prev_rsi_14=66.0,      # Was above 65
            ema_50=97.0,           # Close < EMA50 ✓
            ema_200=100.0,         # Close < EMA200 ✓
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "SHORT"

    def test_no_extreme_rsi(self, strategy):
        """RSI in mid-range (40–60) → None."""
        candles = _make_candle_list(50)
        indicators = _make_indicators(rsi_14=50.0, prev_rsi_14=48.0)
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None

    def test_counter_trend_filter(self, strategy):
        """RSI oversold reversal but price below both EMAs → None."""
        candles = _make_candle_list(49) + [_make_candle(close=85.0)]
        indicators = _make_indicators(
            rsi_14=32.0, prev_rsi_14=28.0,
            ema_50=97.0,     # close (85) < EMA50
            ema_200=100.0,   # close (85) < EMA200
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None

    def test_confidence_with_macd_confirmation(self, strategy):
        """Oversold reversal + positive MACD histogram → higher confidence."""
        candles = _make_candle_list(49) + [_make_candle(close=101.0, volume=1200.0)]
        indicators = _make_indicators(
            rsi_14=36.0, prev_rsi_14=34.0,
            ema_200=90.0,
            macd_histogram=0.5,  # Positive = bullish confirmation
            volume_ma_20=1000.0,
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        # Base 0.55 + MACD 0.15 + vol 0.10 = 0.80
        assert signal.confidence >= 0.75


# =============================================================================
# Bollinger Band Squeeze Tests
# =============================================================================

class TestBollingerSqueeze:
    """Tests for the Bollinger Band Squeeze strategy."""

    @pytest.fixture
    def strategy(self):
        from app.strategies.bollinger_squeeze import BollingerSqueezeStrategy
        return BollingerSqueezeStrategy()

    def test_bullish_breakout(self, strategy):
        """Squeeze → close breaks above upper band + volume → LONG."""
        candles = _make_candle_list(49) + [_make_candle(close=107.0, volume=1500.0)]

        # bb_width_history: narrow widths (squeeze), avg ~0.06
        # prev_bb_width < avg → squeeze was active
        indicators = _make_indicators(
            bb_upper=106.0,
            bb_lower=94.0,
            bb_width=0.12,          # Current: expanding (breakout)
            prev_bb_width=0.04,     # Previous: narrow (squeeze)
            bb_width_history=[0.05, 0.04, 0.06, 0.05, 0.04, 0.05, 0.06, 0.04, 0.05, 0.04,
                              0.06, 0.05, 0.04, 0.05, 0.06, 0.04, 0.05, 0.04, 0.05, 0.04],
            volume_ma_20=1000.0,
            ema_50=97.0,
        )

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "LONG"

    def test_bearish_breakout(self, strategy):
        """Squeeze → close breaks below lower band + volume → SHORT."""
        candles = _make_candle_list(49) + [_make_candle(close=92.0, volume=1500.0)]

        indicators = _make_indicators(
            bb_upper=106.0,
            bb_lower=94.0,
            bb_width=0.12,
            prev_bb_width=0.04,
            bb_width_history=[0.05] * 20,  # avg = 0.05, prev 0.04 < 0.05 = squeeze
            volume_ma_20=1000.0,
            ema_50=97.0,
        )

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "SHORT"

    def test_no_squeeze(self, strategy):
        """Normal width (prev_bb_width >= avg) → None."""
        candles = _make_candle_list(49) + [_make_candle(close=107.0, volume=1500.0)]

        indicators = _make_indicators(
            bb_upper=106.0,
            bb_lower=94.0,
            bb_width=0.12,
            prev_bb_width=0.12,     # Previous width is ABOVE the average
            bb_width_history=[0.10] * 20,  # avg = 0.10, prev 0.12 > 0.10 = NOT squeeze
            volume_ma_20=1000.0,
        )

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None

    def test_breakout_no_volume(self, strategy):
        """Squeeze breakout but weak volume → Low Confidence Signal."""
        candles = _make_candle_list(49) + [_make_candle(close=107.0, volume=800.0)]

        indicators = _make_indicators(
            bb_upper=106.0,
            bb_lower=94.0,
            bb_width=0.12,
            prev_bb_width=0.04,
            bb_width_history=[0.05] * 20,
            volume_ma_20=1000.0,  # 800 < 1000 * 1.2 = 1200 → weak
        )

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert round(signal.confidence, 2) == 0.75  # Base 0.55 + EMA align 0.10 + expanding 0.10

    def test_insufficient_bb_history(self, strategy):
        """Too few bb_width_history values → None."""
        candles = _make_candle_list(49) + [_make_candle(close=107.0, volume=1500.0)]
        indicators = _make_indicators(
            bb_upper=106.0, bb_lower=94.0,
            bb_width=0.12, prev_bb_width=0.04,
            bb_width_history=[0.05] * 5,  # Only 5 values < MIN_BB_HISTORY (10)
            volume_ma_20=1000.0,
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None


# =============================================================================
# MACD Momentum Tests
# =============================================================================

class TestMACDMomentum:
    """Tests for the MACD Momentum strategy."""

    @pytest.fixture
    def strategy(self):
        from app.strategies.macd_momentum import MACDMomentumStrategy
        return MACDMomentumStrategy()

    def test_bullish_cross(self, strategy):
        """MACD crosses above signal, histogram positive → LONG."""
        candles = _make_candle_list(49) + [_make_candle(close=101.0, volume=1100.0)]
        indicators = _make_indicators(
            macd_line=0.6, macd_signal=0.5,           # Current: MACD > signal
            prev_macd_line=0.3, prev_macd_signal=0.4, # Previous: MACD < signal (cross!)
            macd_histogram=0.1,                        # Positive ✓
            prev_macd_histogram=-0.1,                  # Was negative (momentum buildup)
            ema_50=97.0,
            volume_ma_20=1000.0,
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "LONG"

    def test_bearish_cross(self, strategy):
        """MACD crosses below signal, histogram negative → SHORT."""
        candles = _make_candle_list(49) + [_make_candle(close=95.0, volume=1100.0)]
        indicators = _make_indicators(
            macd_line=-0.3, macd_signal=-0.2,         # Current: MACD < signal
            prev_macd_line=0.1, prev_macd_signal=0.0, # Previous: MACD > signal (cross!)
            macd_histogram=-0.1,                       # Negative ✓
            prev_macd_histogram=0.1,                   # Was positive (momentum buildup)
            ema_50=97.0,
            volume_ma_20=1000.0,
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "SHORT"

    def test_no_cross(self, strategy):
        """No MACD crossover → None."""
        candles = _make_candle_list(50)
        indicators = _make_indicators(
            macd_line=0.6, macd_signal=0.5,
            prev_macd_line=0.5, prev_macd_signal=0.4,  # Both above: no cross
            macd_histogram=0.1, prev_macd_histogram=0.1,
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None

    def test_cross_but_histogram_disagrees(self, strategy):
        """Bullish cross but histogram still negative → None."""
        candles = _make_candle_list(50)
        indicators = _make_indicators(
            macd_line=0.6, macd_signal=0.5,
            prev_macd_line=0.3, prev_macd_signal=0.4,  # Cross happened
            macd_histogram=-0.05,                        # But histogram negative!
            prev_macd_histogram=-0.1,
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None


# =============================================================================
# S/R Zone Rejection Tests
# =============================================================================

class TestSRRejection:
    """Tests for the S/R Zone Rejection strategy."""

    @pytest.fixture
    def strategy(self):
        from app.strategies.sr_rejection import SRRejectionStrategy
        return SRRejectionStrategy()

    def _support_zone(self, price=95.0, strength=0.5):
        return {
            'price_level': price,
            'zone_upper': price + 1.0,
            'zone_lower': price - 1.0,
            'zone_type': 'support',
            'strength_score': strength,
        }

    def _resistance_zone(self, price=105.0, strength=0.5):
        return {
            'price_level': price,
            'zone_upper': price + 1.0,
            'zone_lower': price - 1.0,
            'zone_type': 'resistance',
            'strength_score': strength,
        }

    def test_support_bounce(self, strategy):
        """Pin bar at support zone, close above → LONG."""
        # Create a hammer candle: low penetrates zone, close above zone
        # Candle: open=98, high=99, low=94.5 (enters zone at 96), close=98.5
        # lower wick = 98 - 94.5 = 3.5, range = 99 - 94.5 = 4.5, ratio = 0.78 > 0.60 ✓
        candle = _make_candle(open_=98.0, high=99.0, low=94.5, close=98.5)
        candles = _make_candle_list(49) + [candle]
        zone = self._support_zone(price=95.0, strength=0.5)
        indicators = _make_indicators(volume_ma_20=1000.0, rsi_14=45.0)

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is not None
        assert signal.direction == "LONG"

    def test_resistance_rejection(self, strategy):
        """Shooting star at resistance zone, close below → SHORT."""
        # Create a shooting star: high penetrates zone, close below zone
        # Candle: open=103.5, high=106.0 (enters zone at 104), close=103.0, low=102.5
        # upper wick = 106 - 103.5 = 2.5, range = 106 - 102.5 = 3.5, ratio = 0.71 > 0.60 ✓
        candle = _make_candle(open_=103.5, high=106.0, low=102.5, close=103.0)
        candles = _make_candle_list(49) + [candle]
        zone = self._resistance_zone(price=105.0, strength=0.5)
        indicators = _make_indicators(volume_ma_20=1000.0, rsi_14=55.0)

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is not None
        assert signal.direction == "SHORT"

    def test_no_candle_pattern(self, strategy):
        """Price near zone but no rejection candle pattern → None."""
        # Doji-like candle with equal wicks — no dominant wick direction
        candle = _make_candle(open_=96.0, high=97.0, low=95.0, close=96.0)
        candles = _make_candle_list(49) + [candle]
        zone = self._support_zone(price=95.0, strength=0.5)
        indicators = _make_indicators()

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is None

    def test_weak_zone_filtered(self, strategy):
        """Rejection pattern exists but zone strength < 0.3 → None."""
        candle = _make_candle(open_=98.0, high=99.0, low=94.5, close=98.5)
        candles = _make_candle_list(49) + [candle]
        zone = self._support_zone(price=95.0, strength=0.1)  # Too weak
        indicators = _make_indicators()

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is None

    def test_no_zones(self, strategy):
        """No S/R zones provided → None."""
        candles = _make_candle_list(50)
        indicators = _make_indicators()
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is None


# =============================================================================
# S/R Zone Breakout Tests
# =============================================================================

class TestSRBreakout:
    """Tests for the S/R Zone Breakout strategy."""

    @pytest.fixture
    def strategy(self):
        from app.strategies.sr_breakout import SRBreakoutStrategy
        return SRBreakoutStrategy()

    def _resistance_zone(self, price=105.0, strength=0.4):
        return {
            'price_level': price,
            'zone_upper': price + 1.0,
            'zone_lower': price - 1.0,
            'zone_type': 'resistance',
            'strength_score': strength,
        }

    def _support_zone(self, price=95.0, strength=0.4):
        return {
            'price_level': price,
            'zone_upper': price + 1.0,
            'zone_lower': price - 1.0,
            'zone_type': 'support',
            'strength_score': strength,
        }

    def test_resistance_breakout_long(self, strategy):
        """Close breaks above resistance zone with strong body + volume → LONG."""
        # Previous candle: close at 105.5 (below zone upper 106)
        prev_candle = _make_candle(open_=104.0, high=105.5, low=103.5, close=105.5, time_offset_hours=48)
        # Current candle: strong bullish break above zone (close 107.5 > zone_upper 106)
        # Body: |107.5 - 105.0| = 2.5, range: 108 - 105 = 3.0, ratio = 0.83 > 0.50 ✓
        break_candle = _make_candle(open_=105.0, high=108.0, low=105.0, close=107.5, volume=1500.0, time_offset_hours=49)

        candles = _make_candle_list(48) + [prev_candle, break_candle]
        zone = self._resistance_zone(price=105.0, strength=0.4)
        indicators = _make_indicators(volume_ma_20=1000.0, ema_50=97.0)

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is not None
        assert signal.direction == "LONG"

    def test_support_breakout_short(self, strategy):
        """Close breaks below support zone with strong body + volume → SHORT."""
        # Previous candle: close at 94.5 (above zone lower 94)
        prev_candle = _make_candle(open_=96.0, high=96.5, low=94.5, close=94.5, time_offset_hours=48)
        # Current candle: strong bearish break below zone
        # Body: |93.5 - 96.0| = 2.5, range: 96 - 92.5 = 3.5, ratio = 0.71 > 0.50 ✓
        break_candle = _make_candle(open_=96.0, high=96.0, low=92.5, close=93.5, volume=1500.0, time_offset_hours=49)

        candles = _make_candle_list(48) + [prev_candle, break_candle]
        zone = self._support_zone(price=95.0, strength=0.4)
        indicators = _make_indicators(volume_ma_20=1000.0, ema_50=97.0)

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is not None
        assert signal.direction == "SHORT"

    def test_wick_only_no_breakout(self, strategy):
        """High above zone but close inside (wick probe) → None."""
        prev_candle = _make_candle(open_=104.0, high=105.5, low=103.5, close=104.0, time_offset_hours=48)
        # Wick reaches above zone, but body stays inside
        wick_candle = _make_candle(open_=104.5, high=108.0, low=104.0, close=105.0, volume=1500.0, time_offset_hours=49)

        candles = _make_candle_list(48) + [prev_candle, wick_candle]
        zone = self._resistance_zone(price=105.0)
        indicators = _make_indicators(volume_ma_20=1000.0)

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is None

    def test_breakout_no_volume(self, strategy):
        """Breakout candle but weak volume → Low Confidence Signal."""
        prev_candle = _make_candle(open_=104.0, high=105.5, low=103.5, close=105.5, time_offset_hours=48)
        break_candle = _make_candle(open_=105.0, high=108.0, low=105.0, close=107.5, volume=800.0, time_offset_hours=49)

        candles = _make_candle_list(48) + [prev_candle, break_candle]
        zone = self._resistance_zone(price=105.0)
        indicators = _make_indicators(volume_ma_20=1000.0)  # 800 < 1000 * 1.3 = 1300

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is not None
        assert round(signal.confidence, 2) == 0.75  # Base 0.55 + EMA align 0.10 + retest 0.10

    def test_weak_body_no_breakout(self, strategy):
        """Breakout close but weak body (doji-like) → None."""
        prev_candle = _make_candle(open_=104.0, high=105.5, low=103.5, close=105.5, time_offset_hours=48)
        # Doji: body ratio < 0.50
        doji = _make_candle(open_=107.0, high=108.0, low=105.0, close=107.2, volume=1500.0, time_offset_hours=49)
        # body = 0.2, range = 3.0, ratio = 0.067 < 0.50

        candles = _make_candle_list(48) + [prev_candle, doji]
        zone = self._resistance_zone(price=105.0)
        indicators = _make_indicators(volume_ma_20=1000.0)

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is None


# =============================================================================
# Trend Pullback Confluence Tests (incl. Falling Knife Protection)
# =============================================================================

class TestTrendPullbackConfluence:
    """Tests for the Trend Pullback Confluence strategy with velocity filters."""

    @pytest.fixture
    def strategy(self):
        from app.strategies.trend_pullback_confluence import TrendPullbackConfluenceStrategy
        return TrendPullbackConfluenceStrategy()

    def _bullish_setup_indicators(self, atr=2.0, **overrides):
        """Create indicators for a valid bullish pullback scenario."""
        defaults = dict(
            ema_50=100.0, ema_100=98.0, ema_200=95.0,  # Bullish stack
            rsi_14=42.0, prev_rsi_14=38.0,               # RSI hooking up from exhaustion
            rsi_14_history=[38.0, 36.0, 37.0, 39.0, 42.0],  # Recent dip below 45
            atr_14=atr,
            macd_histogram=0.1,
            volume_ma_20=1000.0,
        )
        defaults.update(overrides)
        return _make_indicators(**defaults)

    def test_valid_bullish_pullback(self, strategy):
        """Normal gentle pullback to 50 EMA with RSI hook → LONG signal."""
        # Gentle candle: open=100.5, high=101.0, low=99.8, close=100.3
        # body = 0.2, range = 1.2 — well under 1.8*ATR=3.6 and 1.2*ATR=2.4
        candle = _make_candle(open_=100.5, high=101.0, low=99.8, close=100.3, volume=1200.0)
        candles = _make_candle_list(49) + [candle]
        indicators = self._bullish_setup_indicators(atr=2.0)

        signal = strategy.scan("BTCUSDT", "15m", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "LONG"

    def test_violent_candle_rejected(self, strategy):
        """Candle range > 1.8x ATR crashes into EMA → None (falling knife abort)."""
        # Violent candle: range = 4.0, ATR = 2.0 → 4.0 > 1.8*2.0=3.6 → ABORT
        candle = _make_candle(open_=102.0, high=102.5, low=98.5, close=100.3, volume=1200.0)
        candles = _make_candle_list(49) + [candle]
        indicators = self._bullish_setup_indicators(atr=2.0)

        signal = strategy.scan("BTCUSDT", "15m", candles, indicators, [])
        assert signal is None

    def test_large_body_marubozu_rejected(self, strategy):
        """Body > 1.2x ATR but range under threshold → None (marubozu filter)."""
        # Marubozu: open=103.0, close=100.2, body=2.8, range=3.2
        # ATR=2.0 → range=3.2 < 1.8*2=3.6 (passes range), body=2.8 > 1.2*2=2.4 (rejected!)
        candle = _make_candle(open_=103.0, high=103.2, low=100.0, close=100.2, volume=1200.0)
        candles = _make_candle_list(49) + [candle]
        indicators = self._bullish_setup_indicators(atr=2.0)

        signal = strategy.scan("BTCUSDT", "15m", candles, indicators, [])
        assert signal is None

    def test_valid_bearish_pullback(self, strategy):
        """Normal gentle pullback to 50 EMA (bearish) with RSI hook → SHORT signal."""
        # Gentle bearish candle tagging EMA 50 from below
        candle = _make_candle(open_=99.5, high=100.2, low=99.0, close=99.7, volume=1200.0)
        candles = _make_candle_list(49) + [candle]
        indicators = _make_indicators(
            ema_50=100.0, ema_100=102.0, ema_200=105.0,  # Bearish stack
            rsi_14=58.0, prev_rsi_14=62.0,                 # RSI hooking down
            rsi_14_history=[62.0, 63.0, 61.0, 59.0, 58.0],
            atr_14=2.0,
            macd_histogram=-0.1,
            volume_ma_20=1000.0,
        )

        signal = strategy.scan("BTCUSDT", "15m", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "SHORT"

    def test_gentle_candle_passes(self, strategy):
        """Candle range = 1.5x ATR (under 1.8x threshold) → signal fires."""
        # Range = 3.0, ATR = 2.0 → 3.0/2.0 = 1.5x (under 1.8x)
        # Body = 0.3 (tiny), well under 1.2*2.0 = 2.4
        candle = _make_candle(open_=100.3, high=101.5, low=98.5, close=100.6, volume=1200.0)
        candles = _make_candle_list(49) + [candle]
        indicators = self._bullish_setup_indicators(atr=2.0)

        signal = strategy.scan("BTCUSDT", "15m", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "LONG"


# =============================================================================
# Fibonacci Retracement Tests
# =============================================================================

class TestFibonacciRetracement:
    """Tests for the Fibonacci Retracement strategy."""

    @pytest.fixture
    def strategy(self):
        from app.strategies.fibonacci_retracement import FibonacciRetracementStrategy
        return FibonacciRetracementStrategy()

    def _build_bullish_impulse_candles(self):
        """
        Build a 50-candle window with a clear bullish impulse followed by a retracement
        into the golden pocket.

        Structure:
          - Candles 0-17: Flat base around 92
          - Candles 18-19: Dip into swing low zone
          - Candle 20: Swing low at 90.0 (confirmed pivot)
          - Candles 21-26: Rally from 90 to 108
          - Candle 27: Swing high at 110.0 (confirmed pivot)
          - Candles 28-48: Retracement toward golden pocket
          - Candle 49: Rejection candle in golden pocket

        Swing range = 110 - 90 = 20
        Golden pocket: 50% = 100.0, 61.8% = 97.64
        """
        candles = []

        # Candles 0-17: Flat base around 92
        for i in range(18):
            candles.append(_make_candle(
                close=92.0 + i * 0.05, open_=91.5 + i * 0.05,
                high=93.0 + i * 0.05, low=91.0 + i * 0.05,
                volume=1000.0, time_offset_hours=i,
            ))

        # Candles 18-19: Dip into swing low zone
        candles.append(_make_candle(close=91.0, open_=92.0, high=92.5, low=90.5, volume=1000.0, time_offset_hours=18))
        candles.append(_make_candle(close=90.5, open_=91.0, high=91.5, low=90.3, volume=1000.0, time_offset_hours=19))

        # Candle 20: THE SWING LOW
        candles.append(_make_candle(close=90.5, open_=91.0, high=91.0, low=90.0, volume=1000.0, time_offset_hours=20))

        # Candles 21-23: Rally (lows > 90.0 to confirm swing low pivot)
        candles.append(_make_candle(close=93.0, open_=91.0, high=93.5, low=91.0, volume=1200.0, time_offset_hours=21))
        candles.append(_make_candle(close=96.0, open_=93.0, high=96.5, low=92.5, volume=1300.0, time_offset_hours=22))
        candles.append(_make_candle(close=99.0, open_=96.0, high=99.5, low=95.5, volume=1400.0, time_offset_hours=23))

        # Candles 24-26: Continue rally
        candles.append(_make_candle(close=102.0, open_=99.0, high=102.5, low=98.5, volume=1500.0, time_offset_hours=24))
        candles.append(_make_candle(close=105.0, open_=102.0, high=105.5, low=101.5, volume=1500.0, time_offset_hours=25))
        candles.append(_make_candle(close=108.0, open_=105.0, high=108.5, low=104.5, volume=1500.0, time_offset_hours=26))

        # Candle 27: THE SWING HIGH
        candles.append(_make_candle(close=109.5, open_=108.0, high=110.0, low=107.5, volume=1600.0, time_offset_hours=27))

        # Candles 28-30: Pull back (highs < 110.0 to confirm swing high pivot)
        candles.append(_make_candle(close=108.0, open_=109.0, high=109.5, low=107.5, volume=1200.0, time_offset_hours=28))
        candles.append(_make_candle(close=106.0, open_=108.0, high=108.5, low=105.5, volume=1100.0, time_offset_hours=29))
        candles.append(_make_candle(close=104.0, open_=106.0, high=106.5, low=103.5, volume=1000.0, time_offset_hours=30))

        # Candles 31-48: Continue retracement toward golden pocket
        for i in range(31, 49):
            price = 104.0 - (i - 31) * 0.3
            candles.append(_make_candle(
                close=price, open_=price + 0.3,
                high=price + 0.8, low=price - 0.8,
                volume=1000.0, time_offset_hours=i,
            ))

        # Candle 49: REJECTION CANDLE in golden pocket (~98.8)
        candles.append(_make_candle(
            open_=98.2, high=99.0, low=97.5, close=98.8,
            volume=1500.0, time_offset_hours=49,
        ))

        return candles

    def _build_bearish_impulse_candles(self):
        """
        Build a 50-candle window with a bearish impulse followed by upward
        retracement into the bearish golden pocket.

        Swing high at 110 -> drop to 90 -> retracement up to golden pocket.
        Bearish golden pocket: 50% = 100.0, 61.8% = 102.36
        """
        candles = []

        # Candles 0-17: Flat base around 108
        for i in range(18):
            candles.append(_make_candle(
                close=108.0 - i * 0.05, open_=108.5 - i * 0.05,
                high=109.0 - i * 0.05, low=107.0 - i * 0.05,
                volume=1000.0, time_offset_hours=i,
            ))

        # Candles 18-19: Rally into swing high zone
        candles.append(_make_candle(close=109.0, open_=108.0, high=109.5, low=107.5, volume=1000.0, time_offset_hours=18))
        candles.append(_make_candle(close=109.5, open_=109.0, high=109.8, low=108.5, volume=1000.0, time_offset_hours=19))

        # Candle 20: THE SWING HIGH
        candles.append(_make_candle(close=109.5, open_=109.0, high=110.0, low=109.0, volume=1000.0, time_offset_hours=20))

        # Candles 21-23: Drop (highs < 110 to confirm pivot)
        candles.append(_make_candle(close=107.0, open_=109.0, high=109.0, low=106.5, volume=1200.0, time_offset_hours=21))
        candles.append(_make_candle(close=104.0, open_=107.0, high=107.5, low=103.5, volume=1300.0, time_offset_hours=22))
        candles.append(_make_candle(close=101.0, open_=104.0, high=104.5, low=100.5, volume=1400.0, time_offset_hours=23))

        # Candles 24-26: Continue dropping
        candles.append(_make_candle(close=98.0, open_=101.0, high=101.5, low=97.5, volume=1500.0, time_offset_hours=24))
        candles.append(_make_candle(close=95.0, open_=98.0, high=98.5, low=94.5, volume=1500.0, time_offset_hours=25))
        candles.append(_make_candle(close=92.0, open_=95.0, high=95.5, low=91.5, volume=1500.0, time_offset_hours=26))

        # Candle 27: THE SWING LOW
        candles.append(_make_candle(close=90.5, open_=92.0, high=92.5, low=90.0, volume=1600.0, time_offset_hours=27))

        # Candles 28-30: Retrace up (lows > 90.0 to confirm pivot)
        candles.append(_make_candle(close=92.0, open_=91.0, high=92.5, low=90.5, volume=1200.0, time_offset_hours=28))
        candles.append(_make_candle(close=94.0, open_=92.0, high=94.5, low=91.5, volume=1100.0, time_offset_hours=29))
        candles.append(_make_candle(close=96.0, open_=94.0, high=96.5, low=93.5, volume=1000.0, time_offset_hours=30))

        # Candles 31-48: Continue retracement toward bearish golden pocket
        for i in range(31, 49):
            price = 96.0 + (i - 31) * 0.35
            candles.append(_make_candle(
                close=price, open_=price - 0.3,
                high=price + 0.8, low=price - 0.8,
                volume=1000.0, time_offset_hours=i,
            ))

        # Candle 49: REJECTION CANDLE — bearish, big upper wick (~101.2)
        candles.append(_make_candle(
            open_=101.8, high=102.5, low=101.0, close=101.2,
            volume=1500.0, time_offset_hours=49,
        ))

        return candles

    def test_bullish_golden_pocket_entry(self, strategy):
        """Price retraces into golden pocket after rally with bullish rejection -> LONG."""
        candles = self._build_bullish_impulse_candles()
        indicators = _make_indicators(
            atr_14=2.0, rsi_14=45.0, volume_ma_20=1000.0, ema_200=85.0,
        )
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "LONG"
        assert signal.confidence >= 0.65
        assert "golden pocket" in signal.notes

    def test_bearish_golden_pocket_entry(self, strategy):
        """Price retraces into golden pocket after drop with bearish rejection -> SHORT."""
        candles = self._build_bearish_impulse_candles()
        indicators = _make_indicators(
            atr_14=2.0, rsi_14=55.0, volume_ma_20=1000.0, ema_200=115.0,
        )
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "SHORT"
        assert signal.confidence >= 0.65

    def test_no_impulse_too_small(self, strategy):
        """Swing range < 3x ATR -> None."""
        candles = self._build_bullish_impulse_candles()
        indicators = _make_indicators(atr_14=10.0)
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, [])
        assert signal is None

    def test_no_retracement(self, strategy):
        """Price hasn't pulled back (still near swing high) -> None."""
        candles = self._build_bullish_impulse_candles()
        candles[-1] = _make_candle(
            open_=109.0, high=110.5, low=108.5, close=109.5,
            volume=1500.0, time_offset_hours=49,
        )
        indicators = _make_indicators(atr_14=2.0)
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, [])
        assert signal is None

    def test_no_rejection_candle(self, strategy):
        """Price in golden pocket but no wick rejection pattern -> None."""
        candles = self._build_bullish_impulse_candles()
        candles[-1] = _make_candle(
            open_=99.0, high=99.2, low=98.8, close=98.9,
            volume=1500.0, time_offset_hours=49,
        )
        indicators = _make_indicators(atr_14=2.0)
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, [])
        assert signal is None

    def test_382_level_lower_confidence(self, strategy):
        """Entry at 38.2% level fires with lower base confidence than golden pocket."""
        candles = self._build_bullish_impulse_candles()
        # 38.2% level for bullish = 110 - (20 * 0.382) = 102.36
        candles[-1] = _make_candle(
            open_=102.0, high=102.8, low=101.5, close=102.5,
            volume=1500.0, time_offset_hours=49,
        )
        indicators = _make_indicators(atr_14=2.0, rsi_14=45.0, volume_ma_20=1000.0)
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "LONG"
        assert "38.2%" in signal.notes

    def test_confidence_with_sr_confluence(self, strategy):
        """Golden pocket overlaps an S/R zone -> boosted confidence."""
        candles = self._build_bullish_impulse_candles()
        indicators = _make_indicators(
            atr_14=2.0, rsi_14=45.0, volume_ma_20=1000.0, ema_200=85.0,
        )
        sr_zones = [{'price_level': 99.0, 'zone_type': 'support', 'strength_score': 0.5}]
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, sr_zones)
        assert signal is not None
        assert signal.confidence >= 0.80
        assert "S/R confluence: yes" in signal.notes

    def test_insufficient_candles(self, strategy):
        """Fewer than required candles -> None."""
        candles = _make_candle_list(10)
        indicators = _make_indicators(atr_14=2.0)
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, [])
        assert signal is None

    def test_sl_behind_wick(self, strategy):
        """SL is placed behind the rejection candle's low + 0.5 ATR buffer."""
        candles = self._build_bullish_impulse_candles()
        indicators = _make_indicators(atr_14=2.0, rsi_14=45.0, volume_ma_20=1000.0)
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, [])
        assert signal is not None
        sl = strategy.calculate_sl(signal, candles, 2.0)
        assert sl == round(97.5 - 1.0, 8)

    def test_tp_risk_based(self, strategy):
        """TP1 at 1.5R, TP2 at 3.0R from SL."""
        candles = self._build_bullish_impulse_candles()
        indicators = _make_indicators(atr_14=2.0, rsi_14=45.0, volume_ma_20=1000.0)
        signal = strategy.scan("BTCUSDT", "1h", candles, indicators, [])
        assert signal is not None
        tp1, tp2 = strategy.calculate_tp(signal, candles, 2.0)
        sl = strategy.calculate_sl(signal, candles, 2.0)
        risk = abs(signal.entry - sl)
        assert round(tp1, 4) == round(signal.entry + 1.5 * risk, 4)
        assert round(tp2, 4) == round(signal.entry + 3.0 * risk, 4)


