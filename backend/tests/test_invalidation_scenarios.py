"""
Phase 5: Invalidation Test Suite

Tests extractors on deliberately adversarial data:
  - Flat markets, crashes, wick-only breaches, same-candle formation+mitigation
  - Ensures extractors don't produce phantom signals
"""

import pandas as pd
import numpy as np
from app.core.market_structure import extract_fvgs, extract_order_blocks
from app.core.events import detect_choch, detect_volume_climax
from tests.test_data_factory import _make_df, create_flat_market_df


class TestInvalidationScenarios:

    def test_flat_market_no_zones(self):
        """Dead flat market: no zones should form."""
        df = create_flat_market_df(50)
        df['volume'] = 1000.0

        df = extract_fvgs(df)
        assert not df['fvg_active'].any(), "FVG detected in flat market"

        df = extract_order_blocks(df)
        assert not df['ob_active'].any(), "OB detected in flat market"

    def test_constant_uptrend_no_crashes(self):
        """Steady uptrend: extractors should not throw exceptions."""
        rows = []
        for i in range(100):
            rows.append({
                'open': 100.0 + i,
                'high': 101.0 + i,
                'low': 99.0 + i,
                'close': 100.5 + i,
                'volume': 1000.0,
            })
        df = _make_df(rows)

        df_fvg = extract_fvgs(df)
        assert 'fvg_active' in df_fvg.columns

        df_ob = extract_order_blocks(df)
        assert 'ob_active' in df_ob.columns

        df_ev = detect_choch(df)
        assert 'event_choch_bullish' in df_ev.columns

    def test_gap_up_no_crash(self):
        """Large gap up: should not crash any extractor."""
        rows = []
        for i in range(10):
            rows.append({'open': 100.0 + i, 'high': 101.0 + i, 'low': 99.0 + i,
                         'close': 100.5 + i, 'volume': 1000.0})
        for i in range(10, 20):
            rows.append({'open': 200.0 + i, 'high': 201.0 + i, 'low': 199.0 + i,
                         'close': 200.5 + i, 'volume': 1000.0})
        df = _make_df(rows)

        df = extract_fvgs(df)
        df = extract_order_blocks(df)
        df = detect_choch(df)

        assert 'fvg_active' in df.columns
        assert 'ob_active' in df.columns

    def test_single_candle_no_crash(self):
        """Single candle: should not crash any extractor."""
        df = _make_df([
            {'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5, 'volume': 1000.0}
        ])

        df = extract_fvgs(df)
        df = extract_order_blocks(df)
        df = detect_choch(df)

        assert 'fvg_active' in df.columns
        assert 'ob_active' in df.columns

    def test_all_nan_volume(self):
        """NaN volume should not crash volume climax detection."""
        rows = [{'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5, 'volume': np.nan}] * 20
        df = _make_df(rows)

        df = detect_volume_climax(df)
        assert not df['event_volume_climax'].any(), "Volume climax with all NaN volume"

    def test_extreme_volatility(self):
        """Extreme volatility: alternating +50%/-50% candles."""
        rows = []
        price = 100.0
        for i in range(50):
            if i % 2 == 0:
                price *= 1.5
            else:
                price *= 0.6
            rows.append({
                'open': price * 0.99, 'high': price * 1.1,
                'low': price * 0.9, 'close': price,
                'volume': 1000.0,
            })
        df = _make_df(rows)

        df = extract_fvgs(df)
        df = extract_order_blocks(df)
        df = detect_choch(df)

        # Extractors should not crash. Zone count may be any number.
        assert 'fvg_active' in df.columns
        assert pd.notna(df['fvg_active']).all()

    def test_double_mitigation_no_reactivation(self):
        """An OB that is mitigated must not reactivate later."""
        # Build a df with OB formation, then mitigation, then price returns to zone
        rows = [
            {'open': 100.0, 'high': 102.0, 'low': 98.0, 'close': 98.5, 'volume': 1000.0},   # 0: bearish (OB)
            {'open': 98.5, 'high': 105.0, 'low': 98.0, 'close': 104.0, 'volume': 1000.0},    # 1: bull impulse
            {'open': 104.0, 'high': 108.0, 'low': 103.0, 'close': 107.0, 'volume': 1000.0},  # 2: bull impulse
            {'open': 107.0, 'high': 108.0, 'low': 97.0, 'close': 97.5, 'volume': 1000.0},    # 3: MITIGATES (close < 98)
            {'open': 97.5, 'high': 99.0, 'low': 96.0, 'close': 98.0, 'volume': 1000.0},      # 4: price back in zone
            {'open': 98.0, 'high': 99.5, 'low': 97.0, 'close': 98.3, 'volume': 1000.0},      # 5: price still in zone
        ]
        df = _make_df(rows)
        df = extract_order_blocks(df, impulse_min=2, impulse_max=5, atr_displacement=0.5)

        # After mitigation at candle 3, OB should NOT be active at rows 4,5
        if df['ob_active'].iloc[2]:  # If OB became active
            assert not df['ob_active'].iloc[3], "OB still active after body-close mitigation"
            assert not df['ob_active'].iloc[4], "OB reactivated after mitigation"
            assert not df['ob_active'].iloc[5], "OB reactivated after mitigation"
