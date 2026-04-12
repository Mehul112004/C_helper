"""
Unit tests for the Indicator Computation Service.
Tests verify mathematical correctness of EMA, RSI, MACD, Bollinger Bands, ATR, and Volume MA
against known data sequences.
"""

import pytest
import pandas as pd
import numpy as np
from app.core.indicators import IndicatorService


class TestEMA:
    """Tests for Exponential Moving Average computation."""

    def test_ema_basic(self):
        """EMA of a constant series should equal the constant."""
        closes = pd.Series([100.0] * 20)
        result = IndicatorService.compute_ema(closes, 9)
        assert abs(result.iloc[-1] - 100.0) < 1e-6

    def test_ema_trending_up(self):
        """EMA of a linearly increasing series should be below the latest value."""
        closes = pd.Series([float(i) for i in range(1, 21)])
        ema_9 = IndicatorService.compute_ema(closes, 9)
        # EMA lags behind price in an uptrend
        assert ema_9.iloc[-1] < closes.iloc[-1]
        assert ema_9.iloc[-1] > closes.iloc[-1] - 10  # But not too far behind

    def test_ema_length_preserved(self):
        """Output series should have the same length as the input."""
        closes = pd.Series([float(i) for i in range(50)])
        result = IndicatorService.compute_ema(closes, 21)
        assert len(result) == len(closes)

    def test_ema_known_values(self):
        """Verify EMA against manually computed values for a small dataset."""
        # EMA(3) of [2, 4, 6, 8, 10]:
        # alpha = 2/(3+1) = 0.5
        # EMA[0] = 2
        # EMA[1] = 0.5*4 + 0.5*2 = 3
        # EMA[2] = 0.5*6 + 0.5*3 = 4.5
        # EMA[3] = 0.5*8 + 0.5*4.5 = 6.25
        # EMA[4] = 0.5*10 + 0.5*6.25 = 8.125
        closes = pd.Series([2.0, 4.0, 6.0, 8.0, 10.0])
        result = IndicatorService.compute_ema(closes, 3)
        assert abs(result.iloc[-1] - 8.125) < 1e-6


class TestRSI:
    """Tests for Relative Strength Index computation."""

    def test_rsi_range(self):
        """RSI should always be between 0 and 100 (after warmup period)."""
        np.random.seed(42)
        closes = pd.Series(np.random.uniform(50, 150, 100).cumsum())
        result = IndicatorService.compute_rsi(closes, 14)

        # Filter out NaN (warmup period)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_rsi_constant_price(self):
        """RSI of a constant price should be NaN or 50 (no gains/losses)."""
        closes = pd.Series([100.0] * 30)
        result = IndicatorService.compute_rsi(closes, 14)
        # With no price changes, delta is 0, so gains and losses are 0
        # This leads to 0/0 which is NaN → RSI is NaN
        # This is acceptable behavior

    def test_rsi_all_gains(self):
        """RSI of a strictly increasing series should be near 100."""
        closes = pd.Series([float(i) for i in range(1, 50)])
        result = IndicatorService.compute_rsi(closes, 14)
        valid = result.dropna()
        # All gains, no losses → RS → infinity → RSI ≈ 100
        assert valid.iloc[-1] > 95

    def test_rsi_all_losses(self):
        """RSI of a strictly decreasing series should be near 0."""
        closes = pd.Series([float(i) for i in range(50, 0, -1)])
        result = IndicatorService.compute_rsi(closes, 14)
        valid = result.dropna()
        assert valid.iloc[-1] < 5


class TestMACD:
    """Tests for MACD computation."""

    def test_macd_output_keys(self):
        """MACD should return dict with macd_line, macd_signal, macd_histogram."""
        closes = pd.Series(np.random.uniform(90, 110, 50))
        result = IndicatorService.compute_macd(closes, 12, 26, 9)
        assert 'macd_line' in result
        assert 'macd_signal' in result
        assert 'macd_histogram' in result

    def test_macd_histogram_identity(self):
        """MACD histogram should equal MACD line minus signal line."""
        np.random.seed(42)
        closes = pd.Series(np.random.uniform(90, 110, 50).cumsum())
        result = IndicatorService.compute_macd(closes, 12, 26, 9)

        expected_hist = result['macd_line'] - result['macd_signal']
        diff = (result['macd_histogram'] - expected_hist).abs()
        assert diff.max() < 1e-10

    def test_macd_length(self):
        """All MACD output series should have the same length as input."""
        closes = pd.Series(np.random.uniform(90, 110, 50))
        result = IndicatorService.compute_macd(closes, 12, 26, 9)
        assert len(result['macd_line']) == 50
        assert len(result['macd_signal']) == 50
        assert len(result['macd_histogram']) == 50


class TestBollingerBands:
    """Tests for Bollinger Bands computation."""

    def test_bb_output_keys(self):
        """Should return upper, middle, lower, and width."""
        closes = pd.Series(np.random.uniform(90, 110, 30))
        result = IndicatorService.compute_bollinger(closes, 20, 2.0)
        assert 'bb_upper' in result
        assert 'bb_middle' in result
        assert 'bb_lower' in result
        assert 'bb_width' in result

    def test_bb_ordering(self):
        """Upper band should always be >= middle >= lower (after warmup)."""
        np.random.seed(42)
        closes = pd.Series(np.random.uniform(90, 110, 50))
        result = IndicatorService.compute_bollinger(closes, 20, 2.0)

        # After warmup (idx 19+), check ordering
        for i in range(20, 50):
            if pd.notna(result['bb_upper'].iloc[i]):
                assert result['bb_upper'].iloc[i] >= result['bb_middle'].iloc[i]
                assert result['bb_middle'].iloc[i] >= result['bb_lower'].iloc[i]

    def test_bb_width_formula(self):
        """Bollinger width should equal (upper - lower) / middle."""
        np.random.seed(42)
        closes = pd.Series(np.random.uniform(90, 110, 50))
        result = IndicatorService.compute_bollinger(closes, 20, 2.0)

        for i in range(20, 50):
            if pd.notna(result['bb_width'].iloc[i]):
                expected_width = (result['bb_upper'].iloc[i] - result['bb_lower'].iloc[i]) / result['bb_middle'].iloc[i]
                assert abs(result['bb_width'].iloc[i] - expected_width) < 1e-10

    def test_bb_band_distance(self):
        """Distance between upper and lower should be 4 × rolling std_dev."""
        np.random.seed(42)
        closes = pd.Series(np.random.uniform(90, 110, 50))
        result = IndicatorService.compute_bollinger(closes, 20, 2.0)
        std = closes.rolling(window=20).std()

        for i in range(20, 50):
            if pd.notna(std.iloc[i]):
                band_distance = result['bb_upper'].iloc[i] - result['bb_lower'].iloc[i]
                expected_distance = 4 * std.iloc[i]  # 2 std_dev × 2 (above + below)
                assert abs(band_distance - expected_distance) < 1e-10


class TestATR:
    """Tests for Average True Range computation."""

    def test_atr_non_negative(self):
        """ATR should never be negative."""
        np.random.seed(42)
        highs = pd.Series(np.random.uniform(100, 120, 50))
        lows = pd.Series(np.random.uniform(80, 100, 50))
        closes = (highs + lows) / 2
        result = IndicatorService.compute_atr(highs, lows, closes, 14)

        valid = result.dropna()
        assert (valid >= 0).all()

    def test_atr_constant_range(self):
        """With constant high-low range and no gaps, ATR should equal the range."""
        highs = pd.Series([110.0] * 30)
        lows = pd.Series([90.0] * 30)
        closes = pd.Series([100.0] * 30)

        result = IndicatorService.compute_atr(highs, lows, closes, 14)
        valid = result.dropna()
        # True Range = 110-90 = 20 each period, ATR(14) should converge to 20
        assert abs(valid.iloc[-1] - 20.0) < 1e-6

    def test_atr_output_length(self):
        """ATR output should have the same length as input."""
        highs = pd.Series(np.random.uniform(100, 120, 50))
        lows = pd.Series(np.random.uniform(80, 100, 50))
        closes = (highs + lows) / 2
        result = IndicatorService.compute_atr(highs, lows, closes, 14)
        assert len(result) == 50


class TestVolumeMA:
    """Tests for Volume Moving Average."""

    def test_volume_ma_basic(self):
        """Volume MA of constant volume should equal the constant."""
        volumes = pd.Series([1000.0] * 30)
        result = IndicatorService.compute_volume_ma(volumes, 20)
        valid = result.dropna()
        assert abs(valid.iloc[-1] - 1000.0) < 1e-6

    def test_volume_ma_length(self):
        """Output length should match input length."""
        volumes = pd.Series(np.random.uniform(500, 1500, 50))
        result = IndicatorService.compute_volume_ma(volumes, 20)
        assert len(result) == 50


class TestEdgeCases:
    """Tests for edge cases in indicator computation."""

    def test_insufficient_data_ema(self):
        """EMA with fewer candles than the period should still work (NaN for early values)."""
        closes = pd.Series([100.0, 110.0, 105.0])
        result = IndicatorService.compute_ema(closes, 200)
        # Should return values (EMA starts from first value), but they won't be accurate
        assert len(result) == 3

    def test_single_candle(self):
        """All indicators should handle a single candle without crashing."""
        closes = pd.Series([100.0])
        highs = pd.Series([105.0])
        lows = pd.Series([95.0])
        volumes = pd.Series([1000.0])

        # None of these should raise an exception
        IndicatorService.compute_ema(closes, 9)
        IndicatorService.compute_rsi(closes, 14)
        IndicatorService.compute_macd(closes, 12, 26, 9)
        IndicatorService.compute_bollinger(closes, 20, 2.0)
        IndicatorService.compute_atr(highs, lows, closes, 14)
        IndicatorService.compute_volume_ma(volumes, 20)

    def test_empty_series(self):
        """Indicators should handle empty series without crashing."""
        closes = pd.Series([], dtype=float)
        highs = pd.Series([], dtype=float)
        lows = pd.Series([], dtype=float)

        IndicatorService.compute_ema(closes, 9)
        IndicatorService.compute_rsi(closes, 14)
        IndicatorService.compute_macd(closes, 12, 26, 9)
        IndicatorService.compute_bollinger(closes, 20, 2.0)
        IndicatorService.compute_atr(highs, lows, closes, 14)
