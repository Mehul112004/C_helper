"""
Test Data Factory — Phase 5 Validation

Generates DataFrames with known price patterns for extractor unit tests.
Every pattern is deterministic with known expected output values.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Internal: build DataFrame with standard OHLCV + open_time columns."""
    base_time = datetime(2026, 5, 1, 0, 0)
    for i, row in enumerate(rows):
        row.setdefault('open_time', base_time + timedelta(hours=i))
        row.setdefault('volume', 1000.0)
    df = pd.DataFrame(rows)
    df['open_time'] = pd.to_datetime(df['open_time'])
    return df


def create_bullish_fvg_df() -> pd.DataFrame:
    """
    Bullish FVG: C1.high < C3.low.
    C1: open=100, high=102, low=98,  close=101  (bullish)
    C2: open=101, high=105, low=100, close=104  (bullish impulse)
    C3: open=104, high=108, low=103, close=106  (gap between C1.high=102 and C3.low=103)
    B1: open=106, high=107, low=105, close=105.5 (post-gap, does NOT mitigate)
    
    Expected: FVG zone active from candle 4 (index 3) with upper=103, lower=102
    """
    return _make_df([
        {'open': 100.0, 'high': 102.0, 'low': 98.0,  'close': 101.0},
        {'open': 101.0, 'high': 105.0, 'low': 100.0, 'close': 104.0},
        {'open': 104.0, 'high': 108.0, 'low': 103.0, 'close': 106.0},
        {'open': 106.0, 'high': 107.0, 'low': 105.0, 'close': 105.5},
    ])


def create_bearish_fvg_df() -> pd.DataFrame:
    """
    Bearish FVG: C1.low > C3.high.
    C1: open=100, high=102, low=99,  close=101  (bullish)
    C2: open=101, high=103, low=96,  close=97   (bearish impulse)
    C3: open=97,  high=98,  low=94,  close=95   (gap between C1.low=99 and C3.high=98)
    
    Expected: FVG zone with upper=99, lower=98
    """
    return _make_df([
        {'open': 100.0, 'high': 102.0, 'low': 99.0,  'close': 101.0},
        {'open': 101.0, 'high': 103.0, 'low': 96.0,  'close': 97.0},
        {'open': 97.0,  'high': 98.0,  'low': 94.0,  'close': 95.0},
        {'open': 95.0,  'high': 96.0,  'low': 93.0,  'close': 94.0},
    ])


def create_mitigated_fvg_df() -> pd.DataFrame:
    """
    Bullish FVG forms at candles 0-2, then candle 4 drops into the gap (mitigates).
    
    C0: open=100, high=102, low=98,  close=101
    C1: open=101, high=105, low=100, close=104
    C2: open=104, high=108, low=103, close=106  (FVG forms at index 2)
    C3: open=106, high=107, low=105, close=105   (post-gap, above FVG)
    C4: open=105, high=105.5, low=101, close=104  (WICK drops into FVG → mitigated)
    """
    return _make_df([
        {'open': 100.0, 'high': 102.0, 'low': 98.0,  'close': 101.0},
        {'open': 101.0, 'high': 105.0, 'low': 100.0, 'close': 104.0},
        {'open': 104.0, 'high': 108.0, 'low': 103.0, 'close': 106.0},
        {'open': 106.0, 'high': 107.0, 'low': 105.0, 'close': 105.0},
        {'open': 105.0, 'high': 105.5, 'low': 101.0, 'close': 104.0},
    ])


def create_mitigated_body_only_df() -> pd.DataFrame:
    """
    Like create_mitigated_fvg_df, but candle 4 only wick-touches the zone,
    body stays above. Used to test mitigation_type='body'.
    """
    return _make_df([
        {'open': 100.0, 'high': 102.0, 'low': 98.0,  'close': 101.0},
        {'open': 101.0, 'high': 105.0, 'low': 100.0, 'close': 104.0},
        {'open': 104.0, 'high': 108.0, 'low': 103.0, 'close': 106.0},
        {'open': 106.0, 'high': 107.0, 'low': 105.0, 'close': 105.0},
        {'open': 105.0, 'high': 106.0, 'low': 101.0, 'close': 105.5},  # wick touch, body stays above
    ])


def create_no_event_df() -> pd.DataFrame:
    """Ranging market — no FVGs, no strong trends."""
    rows = []
    for i in range(20):
        rows.append({
            'open': 100.0 + i * 0.1,
            'high': 100.5 + i * 0.1,
            'low': 99.5 + i * 0.1,
            'close': 100.0 + i * 0.1,
        })
    return _make_df(rows)


def create_swing_trend_df(direction: str = 'bullish') -> pd.DataFrame:
    """
    Create a DataFrame with clear swing highs/lows for ChoCh/BOS testing.
    120 candles with well-defined swing structure (gradual trend, clear pivots).
    """
    np.random.seed(42)
    n = 120

    if direction == 'bullish':
        base = np.linspace(100, 150, n) + np.random.normal(0, 0.3, n)
    else:
        base = np.linspace(150, 100, n) + np.random.normal(0, 0.3, n)

    rows = []
    for i in range(n):
        rows.append({
            'open': base[i] - 0.3,
            'high': base[i] + 0.5,
            'low': base[i] - 0.5,
            'close': base[i] + 0.2,
        })
    # Add clear swing point clusters (local peaks and valleys)
    # Swing high at ~index 30
    for j in range(28, 33):
        rows[j]['high'] = max(rows[j]['high'], base[j] + 2.0)
    rows[30]['high'] = base[30] + 3.0
    # Swing low at ~index 60
    for j in range(58, 63):
        rows[j]['low'] = min(rows[j]['low'], base[j] - 2.0)
    rows[60]['low'] = base[60] - 2.5

    return _make_df(rows)


def create_flat_market_df(n: int = 50) -> pd.DataFrame:
    """Dead flat market — all prices equal."""
    rows = [{
        'open': 100.0, 'high': 100.0, 'low': 100.0, 'close': 100.0,
    }] * n
    return _make_df(rows)


def create_volume_climax_df() -> pd.DataFrame:
    """20 candles where candle 15 has 5x normal volume."""
    rows = []
    for i in range(20):
        vol = 5000.0 if i == 15 else 1000.0
        rows.append({
            'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5,
            'volume': vol,
        })
    return _make_df(rows)
