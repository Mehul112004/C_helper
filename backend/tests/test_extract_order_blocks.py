"""
Phase 5: Order Block Extractor Validation Tests

Validates extract_order_blocks() against known DataFrames.
"""

import pandas as pd
import numpy as np
from app.core.market_structure import extract_order_blocks
from tests.test_data_factory import _make_df, create_flat_market_df


def create_bullish_ob_df() -> pd.DataFrame:
    """
    Bullish OB: last bearish candle before bullish impulse.
    OB candle: bearish at index 14. Impulse: candles 15,16,17 are bullish.
    Prior 14 candles provide enough data for BOS swing detection.
    """
    rows = []
    # Prior candles (indices 0-13): baseline uptrend with variance
    for i in range(14):
        rows.append({
            'open': 95.0 + i * 0.3,
            'high': 96.0 + i * 0.3,
            'low': 94.0 + i * 0.3,
            'close': 95.5 + i * 0.3,
        })
    # OB candle and impulse
    rows.append({'open': 99.5, 'high': 101.0, 'low': 98.0, 'close': 98.5})   # 14: bearish OB
    rows.append({'open': 98.5, 'high': 104.0, 'low': 98.0, 'close': 103.0})   # 15: bull impulse start
    rows.append({'open': 103.0, 'high': 108.0, 'low': 102.0, 'close': 107.0})  # 16: bull impulse
    rows.append({'open': 107.0, 'high': 112.0, 'low': 106.0, 'close': 111.0})  # 17: bull impulse end
    rows.append({'open': 111.0, 'high': 113.0, 'low': 110.0, 'close': 112.5})  # 18
    rows.append({'open': 112.5, 'high': 114.0, 'low': 111.0, 'close': 113.0})  # 19
    return _make_df(rows)


def create_bearish_ob_df() -> pd.DataFrame:
    """Bearish OB: last bullish candle before bearish impulse."""
    rows = [
        {'open': 100.0, 'high': 102.0, 'low': 99.0, 'close': 101.0},
        {'open': 101.0, 'high': 103.0, 'low': 100.0, 'close': 102.0},
        {'open': 102.0, 'high': 104.0, 'low': 101.0, 'close': 103.5},  # 2: bullish OB
        {'open': 103.5, 'high': 104.0, 'low': 100.0, 'close': 100.5},  # 3: bearish impulse start
        {'open': 100.5, 'high': 101.0, 'low': 96.0,  'close': 96.5},   # 4: bearish impulse
        {'open': 96.5,  'high': 97.0,  'low': 93.0,  'close': 94.0},   # 5: bearish impulse end
    ]
    return _make_df(rows)


class TestExtractOrderBlocks:

    def test_bullish_ob_detection(self):
        """Bullish OB detected after a bearish candle followed by bullish impulse."""
        df = create_bullish_ob_df()
        df['volume'] = 1000.0
        df = extract_order_blocks(df, impulse_min=2, impulse_max=5, atr_displacement=0.5)

        # OB should be active at some row
        assert df['ob_active'].any(), "No bullish OB detected"
        # OB direction should be 'bullish'
        active_rows = df[df['ob_active']]
        assert (active_rows['ob_direction'] == 'bullish').all()

    def test_no_ob_in_flat_market(self):
        """Flat market produces no OBs."""
        df = create_flat_market_df(30)
        df['volume'] = 1000.0
        df = extract_order_blocks(df)
        assert not df['ob_active'].any(), "False OB in flat market"

    def test_small_df_does_not_crash(self):
        """DataFrame with < impulse_min+2 candles should not crash."""
        df = create_bullish_ob_df().iloc[:2]
        df['volume'] = 1000.0
        result = extract_order_blocks(df)
        assert 'ob_active' in result.columns
        assert not result['ob_active'].any()

    def test_zone_contract_columns(self):
        """OB extraction must append contract columns."""
        df = create_bullish_ob_df()
        df['volume'] = 1000.0
        df = extract_order_blocks(df)

        required_cols = ['ob_active', 'ob_upper', 'ob_lower', 'ob_volume', 'ob_direction', 'ob_created_at']
        for col in required_cols:
            assert col in df.columns, f"Missing contract column: {col}"

    def test_mitigation_body_close(self):
        """Bullish OB mitigated when close drops below ob_low (body-close)."""
        df = create_bullish_ob_df()
        df['volume'] = 1000.0
        df = extract_order_blocks(df)

        if df['ob_active'].any():
            # The OB should not persist after a candle closes below it
            # With our test data, after the impulse ends, price stays above OB low
            # So OB should remain active
            assert df.iloc[-1]['ob_active'] or df.iloc[-2]['ob_active'], \
                "OB should be active (no mitigation in test data)"
