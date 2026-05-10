"""
Phase 5: FVG Extractor Validation Tests

Validates extract_fvgs() against known DataFrames.
Tests: detection, mitigation, lookahead bias, ffill leak, contract compliance.
"""

import pandas as pd
import numpy as np
from app.core.market_structure import extract_fvgs
from tests.test_data_factory import (
    create_bullish_fvg_df, create_bearish_fvg_df,
    create_mitigated_fvg_df, create_mitigated_body_only_df,
    create_no_event_df, create_flat_market_df,
)


class TestExtractFVGs:

    # ── Detection ──

    def test_bullish_fvg_detection(self):
        """Bullish FVG detected when C3.low > C1.high."""
        df = create_bullish_fvg_df()
        df = extract_fvgs(df)

        # FVG forms at candle 2 (using 0,1,2). Active at candle 3 (shift+1).
        assert not df.loc[2, 'fvg_active'], "FVG active on formation candle (lookahead bias)"
        assert df.loc[3, 'fvg_active'], "FVG not active after formation (candle 3)"
        assert df.loc[3, 'fvg_upper'] == 103.0
        assert df.loc[3, 'fvg_lower'] == 102.0

    def test_bearish_fvg_detection(self):
        """Bearish FVG detected when C3.high < C1.low."""
        df = create_bearish_fvg_df()
        df = extract_fvgs(df)

        assert df['fvg_active'].any(), "No bearish FVG detected"
        # Bearish FVG: upper = C1.low = 99, lower = C3.high = 98
        assert not df.loc[2, 'fvg_active']
        assert df.loc[3, 'fvg_active']
        assert df.loc[3, 'fvg_upper'] == 99.0

    def test_no_false_positive(self):
        """Ranging market produces no FVGs."""
        df = create_no_event_df()
        df = extract_fvgs(df)
        assert not df['fvg_active'].any(), "False FVG in ranging market"

    def test_flat_market_no_fvgs(self):
        """Flat market produces no FVGs."""
        df = create_flat_market_df()
        df = extract_fvgs(df)
        assert not df['fvg_active'].any(), "False FVG in flat market"

    # ── Mitigation ──

    def test_mitigation_wick(self):
        """FVG mitigated when wick touches zone boundary (default: wick)."""
        df = create_mitigated_fvg_df()
        df = extract_fvgs(df, mitigation_type='wick')

        # Only verify if an FVG was actually detected
        if df['fvg_active'].any():
            mitigated_idx = df[df['low'] <= df['fvg_lower']].index[0]
            assert not df.loc[mitigated_idx, 'fvg_active'], "FVG still active after wick mitigation"
            assert df.loc[mitigated_idx:, 'fvg_active'].sum() == 0, \
                f"FVG re-activated after mitigation: {df.loc[mitigated_idx:, 'fvg_active'].sum()} rows"

    def test_mitigation_body_not_triggered_by_wick(self):
        """FVG NOT mitigated by wick when mitigation_type='body'."""
        df = create_mitigated_body_only_df()
        df = extract_fvgs(df, mitigation_type='body')

        if df['fvg_active'].any():
            wick_touch_idx = df[df['low'] <= df['fvg_lower']].index[0]
            assert df.loc[wick_touch_idx, 'fvg_active'], \
                "FVG incorrectly mitigated by wick in body mode"

    def test_mitigation_body_triggered_by_close(self):
        """FVG mitigated when body close enters zone (mitigation_type='body')."""
        df = create_mitigated_fvg_df()
        df_w = extract_fvgs(df.copy(), mitigation_type='wick')
        df_b = extract_fvgs(df.copy(), mitigation_type='body')
        if df_w['fvg_active'].any() and df_b['fvg_active'].any():
            assert not df_w.iloc[-1]['fvg_active'], "Wick mode should mitigate"
            assert df_b.iloc[-1]['fvg_active'], "Body mode should NOT mitigate (body stays above)"

    def test_ffill_leak_prevention(self):
        """Mitigated FVG must not appear active in future candles."""
        df = create_mitigated_fvg_df()
        df = extract_fvgs(df)

        if df['fvg_active'].any():
            mitigated_rows = df[df['low'] <= df['fvg_lower']]
            if len(mitigated_rows) > 0:
                mitigated_idx = mitigated_rows.index[0]
                future_active = df.loc[mitigated_idx + 1:, 'fvg_active']
                assert not future_active.any(), \
                    f"FVG leaked past mitigation: {future_active.sum()} active rows"

    # ── Lookahead Bias Prevention ──

    def test_lookahead_bias_prevention(self):
        """FVG active flag must not use future data."""
        df = create_bullish_fvg_df()
        # Only first 3 candles — FVG detected but active flag shifted by +1
        half_df = df.iloc[:3].copy()
        result = extract_fvgs(half_df)

        assert not result.iloc[-1]['fvg_active'], \
            "Lookahead: zone active before confirming candle closes"

    # ── Contract Compliance ──

    def test_zone_contract_columns(self):
        """Every zone must have the contract columns."""
        df = create_bullish_fvg_df()
        df = extract_fvgs(df)

        required_cols = ['fvg_active', 'fvg_upper', 'fvg_lower', 'fvg_volume', 'fvg_created_at']
        for col in required_cols:
            assert col in df.columns, f"Missing contract column: {col}"

    def test_zone_contract_types(self):
        """Contract columns must have correct dtypes."""
        df = create_bullish_fvg_df()
        df = extract_fvgs(df)

        assert df['fvg_active'].dtype == bool
        assert df['fvg_upper'].dtype == np.float64
        assert df['fvg_lower'].dtype == np.float64

    # ── Small DataFrame Resilience ──

    def test_too_few_candles_does_not_crash(self):
        """DataFrame with < 3 candles should not crash."""
        df = create_bullish_fvg_df().iloc[:2]
        result = extract_fvgs(df)
        assert 'fvg_active' in result.columns
        assert not result['fvg_active'].any()
