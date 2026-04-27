"""
Unit tests for the S/R Zone Detection Engine.
Tests verify swing point detection, round number generation,
zone merging, and strength scoring logic.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.core.sr_engine import SREngine, TIMEFRAME_WEIGHTS


def _make_candle_df(data_points: list[dict]) -> pd.DataFrame:
    """Helper to create a candle DataFrame from a list of dicts."""
    df = pd.DataFrame(data_points)
    df['open_time'] = pd.to_datetime(df['open_time'])
    return df


def _make_synthetic_candles(
    n: int = 100,
    base_price: float = 100.0,
    volatility: float = 2.0,
    seed: int = 42
) -> pd.DataFrame:
    """
    Generate synthetic OHLCV candle data with controlled swing points.
    """
    np.random.seed(seed)
    dates = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)]

    closes = [base_price]
    for i in range(1, n):
        change = np.random.uniform(-volatility, volatility)
        closes.append(closes[-1] + change)

    closes = np.array(closes)
    highs = closes + np.random.uniform(0.5, 1.5, n)
    lows = closes - np.random.uniform(0.5, 1.5, n)
    opens = closes + np.random.uniform(-0.5, 0.5, n)
    volumes = np.random.uniform(1000, 5000, n)

    df = pd.DataFrame({
        'open_time': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    })
    return df


class TestSwingPointDetection:
    """Tests for swing high/low detection."""

    def test_obvious_swing_high(self):
        """A clear peak surrounded by lower values should be detected as a swing high."""
        # Create a V-shape: descending → peak → descending
        #   prices: 100, 99, 98, 97, 96, [105], 96, 97, 98, 99, 100
        # The high at index 5 (105) should be a swing high with lookback=5
        n = 11
        dates = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)]
        highs = [100, 99, 98, 97, 96, 105, 96, 97, 98, 99, 100]
        lows = [v - 1 for v in highs]
        closes = [v - 0.5 for v in highs]

        df = pd.DataFrame({
            'open_time': dates,
            'high': highs,
            'low': lows,
            'close': closes,
        })

        zones = SREngine.detect_swing_points(df, lookback=5)
        resistance_zones = [z for z in zones if z['zone_type'] == 'resistance']

        assert len(resistance_zones) >= 1
        assert any(z['price_level'] == 105.0 for z in resistance_zones)

    def test_obvious_swing_low(self):
        """A clear trough surrounded by higher values should be detected as a swing low."""
        n = 11
        dates = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)]
        lows = [100, 99, 98, 97, 96, 85, 96, 97, 98, 99, 100]
        highs = [v + 1 for v in lows]
        closes = [v + 0.5 for v in lows]

        df = pd.DataFrame({
            'open_time': dates,
            'high': highs,
            'low': lows,
            'close': closes,
        })

        zones = SREngine.detect_swing_points(df, lookback=5)
        support_zones = [z for z in zones if z['zone_type'] == 'support']

        assert len(support_zones) >= 1
        assert any(z['price_level'] == 85.0 for z in support_zones)

    def test_no_swing_in_monotonic_trend(self):
        """A strictly increasing series should have no swing highs in the interior."""
        n = 20
        dates = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)]
        highs = [100 + i * 2 for i in range(n)]
        lows = [100 + i * 2 - 1 for i in range(n)]
        closes = [100 + i * 2 - 0.5 for i in range(n)]

        df = pd.DataFrame({
            'open_time': dates,
            'high': highs,
            'low': lows,
            'close': closes,
        })

        zones = SREngine.detect_swing_points(df, lookback=3)
        resistance_zones = [z for z in zones if z['zone_type'] == 'resistance']
        # In a strict uptrend, no interior candle should be a swing high
        assert len(resistance_zones) == 0

    def test_lookback_parameter(self):
        """Larger lookback should produce fewer, more significant swing points."""
        df = _make_synthetic_candles(200, base_price=100.0, volatility=3.0)

        zones_small = SREngine.detect_swing_points(df, lookback=3)
        zones_large = SREngine.detect_swing_points(df, lookback=10)

        # Larger lookback should yield fewer swing points
        assert len(zones_large) <= len(zones_small)

    def test_zone_type_values(self):
        """All returned zones should have valid zone_type values."""
        df = _make_synthetic_candles(100)
        zones = SREngine.detect_swing_points(df, lookback=5)

        for zone in zones:
            assert zone['zone_type'] in ('support', 'resistance')
            assert zone['detection_method'] == 'swing'
            assert 'price_level' in zone
            assert 'timestamp' in zone


class TestRoundNumbers:
    """Tests for round psychological number detection."""

    def test_btc_round_numbers(self):
        """BTC round numbers should be at $1000 and $5000 increments."""
        zones = SREngine.detect_round_numbers('BTCUSDT', 67000.0)

        levels = [z['price_level'] for z in zones]
        # Should include levels like 65000, 66000, 67000, 68000, etc.
        assert 65000.0 in levels
        assert 70000.0 in levels

    def test_eth_round_numbers(self):
        """ETH round numbers should be at $100 and $500 increments."""
        zones = SREngine.detect_round_numbers('ETHUSDT', 3400.0)

        levels = [z['price_level'] for z in zones]
        assert 3000.0 in levels
        assert 3500.0 in levels

    def test_sol_round_numbers(self):
        """SOL round numbers should be at $10 and $50 increments."""
        zones = SREngine.detect_round_numbers('SOLUSDT', 150.0)

        levels = [z['price_level'] for z in zones]
        assert 140.0 in levels
        assert 150.0 in levels
        assert 160.0 in levels

    def test_xrp_round_numbers(self):
        """XRP round numbers should be at $0.10 and $0.50 increments."""
        zones = SREngine.detect_round_numbers('XRPUSDT', 0.65)

        levels = [round(z['price_level'], 2) for z in zones]
        # At price 0.65, ±15% range is ~0.55 to ~0.75
        assert 0.60 in levels
        assert 0.70 in levels

    def test_round_numbers_range(self):
        """Generated levels should be within ±15% of the current price."""
        current_price = 67000.0
        zones = SREngine.detect_round_numbers('BTCUSDT', current_price, range_pct=0.15)

        for zone in zones:
            assert zone['price_level'] >= current_price * 0.85
            assert zone['price_level'] <= current_price * 1.15

    def test_round_numbers_no_duplicates(self):
        """No duplicate price levels should be returned."""
        zones = SREngine.detect_round_numbers('BTCUSDT', 67000.0)
        levels = [z['price_level'] for z in zones]
        assert len(levels) == len(set(levels))

    def test_round_numbers_zone_type(self):
        """Levels below current price should be support, above should be resistance."""
        current_price = 67000.0
        zones = SREngine.detect_round_numbers('BTCUSDT', current_price)

        for zone in zones:
            if zone['price_level'] < current_price:
                assert zone['zone_type'] == 'support'
            elif zone['price_level'] > current_price:
                assert zone['zone_type'] == 'resistance'

    def test_unknown_symbol_fallback(self):
        """Unknown symbols should use the default round number config."""
        zones = SREngine.detect_round_numbers('DOGEUSDT', 0.15)
        # Should not crash — uses DEFAULT_ROUND_CONFIG
        assert isinstance(zones, list)


class TestZoneMerging:
    """Tests for zone merging logic."""

    def test_merge_nearby_zones(self):
        """Zones within 0.5 × ATR should be merged."""
        atr = 100.0
        zones = [
            {'price_level': 1000.0, 'zone_type': 'support', 'detection_method': 'swing', 'timestamp': datetime.now()},
            {'price_level': 1020.0, 'zone_type': 'support', 'detection_method': 'swing', 'timestamp': datetime.now()},
        ]
        # 1020 - 1000 = 20, which is < 0.5 * 100 = 50 → should merge

        result = SREngine.merge_zones(zones, atr)
        assert len(result) == 1
        # Merged price should be average
        assert abs(result[0]['price_level'] - 1010.0) < 1e-6

    def test_no_merge_distant_zones(self):
        """Zones far apart should not be merged."""
        atr = 100.0
        zones = [
            {'price_level': 1000.0, 'zone_type': 'support', 'detection_method': 'swing', 'timestamp': datetime.now()},
            {'price_level': 1200.0, 'zone_type': 'resistance', 'detection_method': 'swing', 'timestamp': datetime.now()},
        ]
        # 1200 - 1000 = 200, which is > 0.5 * 100 = 50 → should NOT merge

        result = SREngine.merge_zones(zones, atr)
        assert len(result) == 2

    def test_merge_mixed_types_becomes_both(self):
        """Merging a support and resistance zone should result in type 'both'."""
        atr = 100.0
        zones = [
            {'price_level': 1000.0, 'zone_type': 'support', 'detection_method': 'swing', 'timestamp': datetime.now()},
            {'price_level': 1010.0, 'zone_type': 'resistance', 'detection_method': 'swing', 'timestamp': datetime.now()},
        ]

        result = SREngine.merge_zones(zones, atr)
        assert len(result) == 1
        assert result[0]['zone_type'] == 'both'

    def test_merge_empty_list(self):
        """Merging an empty list should return an empty list."""
        result = SREngine.merge_zones([], 100.0)
        assert result == []


class TestZoneWidth:
    """Tests for zone width calculation."""

    def test_zone_width_symmetric(self):
        """Zone should be symmetric around the price level."""
        upper, lower = SREngine.calculate_zone_width(100.0, 20.0)
        assert upper == 105.0  # 100 + 0.25 * 20
        assert lower == 95.0   # 100 - 0.25 * 20

    def test_zone_width_with_zero_atr(self):
        """Zero ATR should result in point zone (upper == lower == price)."""
        upper, lower = SREngine.calculate_zone_width(100.0, 0.0)
        assert upper == 100.0
        assert lower == 100.0


class TestStrengthScoring:
    """Tests for zone strength scoring."""

    def test_higher_timeframe_scores_higher(self):
        """A 1D zone should score higher than a 15m zone with the same touch count."""
        df = _make_synthetic_candles(50, base_price=100.0)

        zone_1d = {
            'price_level': 100.0,
            'zone_upper': 101.0,
            'zone_lower': 99.0,
        }
        zone_15m = {
            'price_level': 100.0,
            'zone_upper': 101.0,
            'zone_lower': 99.0,
        }

        scored_1d = SREngine.score_zone(zone_1d.copy(), df, '1d')
        scored_15m = SREngine.score_zone(zone_15m.copy(), df, '15m')

        # Same touch count but 1D has higher timeframe weight
        assert scored_1d['strength_score'] >= scored_15m['strength_score']
        assert TIMEFRAME_WEIGHTS['1d'] > TIMEFRAME_WEIGHTS['15m']

    def test_strength_capped_at_1(self):
        """Strength score should never exceed 1.0."""
        df = _make_synthetic_candles(200, base_price=100.0, volatility=0.5)

        zone = {
            'price_level': 100.0,
            'zone_upper': 200.0,  # Very wide zone to maximize touches
            'zone_lower': 0.0,
        }

        scored = SREngine.score_zone(zone, df, '1d')
        assert scored['strength_score'] <= 1.0

    def test_touch_count_is_integer(self):
        """Touch count should always be a non-negative integer."""
        df = _make_synthetic_candles(50)
        zone = {
            'price_level': 100.0,
            'zone_upper': 101.0,
            'zone_lower': 99.0,
        }

        scored = SREngine.score_zone(zone, df, '4h')
        assert isinstance(scored['touch_count'], int)
        assert scored['touch_count'] >= 0

    def test_timeframe_weight_values(self):
        """Verify all expected timeframes have weights defined."""
        expected_timeframes = ['1d', '4h', '1h', '15m', '5m']
        for tf in expected_timeframes:
            assert tf in TIMEFRAME_WEIGHTS
            assert 0 < TIMEFRAME_WEIGHTS[tf] <= 1.0
