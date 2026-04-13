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
        """RSI crosses above 30 from oversold → LONG signal."""
        candles = _make_candle_list(49) + [_make_candle(close=101.0)]
        indicators = _make_indicators(
            rsi_14=32.0,           # Now above 30
            prev_rsi_14=28.0,      # Was below 30
            ema_50=97.0,           # Close > EMA50 ✓
            ema_200=90.0,          # Close > EMA200 ✓
        )
        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [])
        assert signal is not None
        assert signal.direction == "LONG"

    def test_overbought_reversal(self, strategy):
        """RSI crosses below 70 from overbought → SHORT signal."""
        candles = _make_candle_list(49) + [_make_candle(close=95.0)]
        indicators = _make_indicators(
            rsi_14=68.0,           # Now below 70
            prev_rsi_14=72.0,      # Was above 70
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
            rsi_14=32.0, prev_rsi_14=28.0,
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
        """Squeeze breakout but weak volume → None."""
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
        assert signal is None

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
        """Breakout candle but weak volume → None."""
        prev_candle = _make_candle(open_=104.0, high=105.5, low=103.5, close=105.5, time_offset_hours=48)
        break_candle = _make_candle(open_=105.0, high=108.0, low=105.0, close=107.5, volume=800.0, time_offset_hours=49)

        candles = _make_candle_list(48) + [prev_candle, break_candle]
        zone = self._resistance_zone(price=105.0)
        indicators = _make_indicators(volume_ma_20=1000.0)  # 800 < 1000 * 1.3 = 1300

        signal = strategy.scan("BTCUSDT", "4h", candles, indicators, [zone])
        assert signal is None

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
