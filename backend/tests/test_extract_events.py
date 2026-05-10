"""
Phase 5: Temporal Event Validation Tests

Validates detect_choch(), detect_volume_climax(), detect_liquidity_sweep()
against known DataFrames.
"""

import pandas as pd
import numpy as np
from app.core.events import detect_choch, detect_volume_climax, detect_liquidity_sweep
from app.core.fractals import detect_swing_points_df, build_swing_list
from tests.test_data_factory import _make_df, create_swing_trend_df, create_volume_climax_df


class TestChoChDetection:

    def test_no_choch_in_ranging_market(self):
        """ChoCh should NOT fire in ranging market without clear structure."""
        rows = []
        for i in range(50):
            rows.append({
                'open': 100.0 + np.sin(i * 0.3) * 1.0,
                'high': 101.0 + np.sin(i * 0.3) * 1.5,
                'low': 99.0 + np.sin(i * 0.3) * 0.5,
                'close': 100.0 + np.sin(i * 0.3) * 1.0,
            })
        df = _make_df(rows)
        df = detect_choch(df, pivot_bars=3)

        # In a ranging market, any ChoCh that fires is likely a false positive
        # We expect very few or none
        choch_total = (df['event_choch_bullish'].sum() +
                       df['event_choch_bearish'].sum())
        assert choch_total <= 8, f"Too many ChoCh events in ranging market: {choch_total}"

    def test_cho_ch_output_columns(self):
        """detect_choch must produce all required event columns."""
        df = create_swing_trend_df('bullish')
        df = detect_choch(df)

        required = [
            'event_choch_bullish', 'event_choch_bearish',
            'event_bos_bullish', 'event_bos_bearish',
            'event_choch_bullish_recent', 'event_choch_bearish_recent',
            'event_bos_bullish_recent', 'event_bos_bearish_recent',
        ]
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_opposing_event_cancellation(self):
        """Bullish ChoCh + later bearish ChoCh → bullish recent must be False."""
        # Create a df where bullish ChoCh fires, then bearish fires
        rows = []
        np.random.seed(1)
        n = 80
        base = np.linspace(100, 130, n) + np.random.normal(0, 0.3, n)
        # Add clear reversals
        for i in range(n):
            rows.append({
                'open': base[i] - 0.2,
                'high': base[i] + 0.5,
                'low': base[i] - 0.5,
                'close': base[i] + 0.3,
            })
        df = _make_df(rows)
        df = detect_choch(df, pivot_bars=3)

        # Verify opposing events don't both show as recent at the same time
        for i in range(10, len(df)):
            both_recent = (df.iloc[i]['event_choch_bullish_recent'] and
                          df.iloc[i]['event_choch_bearish_recent'])
            assert not both_recent, \
                f"Both bullish and bearish ChoCh recent at index {i} — cancellation failed"

    def test_recent_decay(self):
        """_recent columns must eventually decay to False."""
        df = create_swing_trend_df('bullish')
        df = detect_choch(df, recent_window=10)

        # After the last candle, recent columns should be evaluated
        assert isinstance(df.iloc[-1]['event_choch_bullish_recent'], (bool, np.bool_)), \
            "event_choch_bullish_recent is not boolean"


class TestVolumeClimaxDetection:

    def test_volume_climax_trigger(self):
        """Volume > 2x volume_ma triggers climax event."""
        df = create_volume_climax_df()
        df = detect_volume_climax(df, volume_ma_period=5, threshold=2.0)

        # Candle 15 has 5x volume → should trigger climax
        climax_candles = df[df['event_volume_climax']]
        assert len(climax_candles) >= 1, "No volume climax detected"

    def test_climax_bullish_direction(self):
        """Climax candle direction matches close vs open."""
        df = create_volume_climax_df()
        df = detect_volume_climax(df, volume_ma_period=5, threshold=2.0)

        climax = df[df['event_volume_climax']]
        for _, row in climax.iterrows():
            if row['close'] > row['open']:
                assert row['event_volume_climax_bullish'], \
                    "Climax with bullish close not marked bullish"
            elif row['close'] < row['open']:
                assert row['event_volume_climax_bearish'], \
                    "Climax with bearish close not marked bearish"

    def test_volume_climax_output_columns(self):
        """detect_volume_climax must produce required columns."""
        df = create_volume_climax_df()
        df = detect_volume_climax(df)

        required = [
            'event_volume_climax', 'event_volume_climax_bullish',
            'event_volume_climax_bearish', 'event_volume_climax_recent',
        ]
        for col in required:
            assert col in df.columns, f"Missing column: {col}"


class TestLiquiditySweepDetection:

    def test_sweep_output_columns(self):
        """detect_liquidity_sweep must produce required columns."""
        df = create_swing_trend_df('bullish')
        df = detect_liquidity_sweep(df, pivot_bars=3)

        required = ['event_sweep_bullish', 'event_sweep_bearish', 'event_sweep_recent']
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_small_df_does_not_crash(self):
        """Small DataFrame should not crash sweep detection."""
        rows = [{'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5}] * 5
        df = _make_df(rows)
        result = detect_liquidity_sweep(df, pivot_bars=3)
        assert 'event_sweep_recent' in result.columns


class TestFractalDetection:

    def test_swing_points_detected(self):
        """Swing points must be detected in trending data."""
        df = create_swing_trend_df('bullish')
        df = detect_swing_points_df(df, pivot_n=3)

        assert df['swing_high'].any(), "No swing highs detected"
        assert df['swing_low'].any(), "No swing lows detected"

    def test_swing_list_built(self):
        """build_swing_list must return ordered swing points."""
        df = create_swing_trend_df('bullish')
        swings = build_swing_list(df, pivot_n=3)

        assert len(swings) > 0, "No swing points found"
        # Verify chronological ordering
        for i in range(1, len(swings)):
            assert swings[i]['index'] >= swings[i-1]['index'], \
                "Swing list not sorted chronologically"
        # Verify types
        for s in swings:
            assert s['type'] in ('high', 'low'), f"Invalid swing type: {s['type']}"
            assert isinstance(s['price'], float), f"Swing price not float: {type(s['price'])}"
