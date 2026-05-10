"""
Fractal and swing detection utilities.
Shared across multiple strategy modules (SMC, Fibonacci, etc.).
Provides both Candle-object and DataFrame-based APIs.
"""

import pandas as pd
import numpy as np
from typing import Optional
from app.core.base_strategy import Candle


# ── Candle-object API (existing, maintained for backward compatibility) ──

def find_fractal_points(
    candles: list[Candle],
    pivot_n: int
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """
    Find fractal highs and lows in a list of candles.

    A fractal high exists at index `i` if `candle[i].high` is strictly greater
    than the highs of all candles within `±pivot_n` bars.

    A fractal low exists at index `i` if `candle[i].low` is strictly less
    than the lows of all candles within `±pivot_n` bars.

    Returns:
        (fractal_highs, fractal_lows): Two lists of (index, price) tuples.
    """
    fractal_highs = []
    fractal_lows = []

    for i in range(pivot_n, len(candles) - pivot_n):
        is_high = True
        for j in range(1, pivot_n + 1):
            if candles[i].high <= candles[i - j].high or candles[i].high <= candles[i + j].high:
                is_high = False
                break
        if is_high:
            fractal_highs.append((i, candles[i].high))

        is_low = True
        for j in range(1, pivot_n + 1):
            if candles[i].low >= candles[i - j].low or candles[i].low >= candles[i + j].low:
                is_low = False
                break
        if is_low:
            fractal_lows.append((i, candles[i].low))

    return fractal_highs, fractal_lows


def build_swing_map(
    candles: list[Candle],
    pivot_n: int
) -> list[dict]:
    """
    Build an ordered list of swing points using fractal pivot detection.

    Returns a unified list sorted chronologically by index:
    [{'type': 'high'|'low', 'price': float, 'index': int}, ...]
    """
    highs, lows = find_fractal_points(candles, pivot_n)

    swings = []
    for idx, price in highs:
        swings.append({'type': 'high', 'price': price, 'index': idx})
    for idx, price in lows:
        swings.append({'type': 'low', 'price': price, 'index': idx})

    swings.sort(key=lambda s: s['index'])
    return swings


# ── DataFrame API (Phase 1: vectorized extraction layer) ──

def detect_swing_points_df(
    df: pd.DataFrame,
    pivot_n: int = 3,
    price_tolerance: float = 0.0,
) -> pd.DataFrame:
    """
    Detect fractal swing highs and lows from a DataFrame.
    Returns the DataFrame with boolean mask columns appended.

    Args:
        df: DataFrame with columns ['high', 'low']
        pivot_n: Bars on each side of the pivot (default 3)
        price_tolerance: Fractional tolerance for nearby price equality (0=strict)

    Returns:
        DataFrame with added columns:
            swing_high: bool — True at fractal swing high
            swing_low:  bool — True at fractal swing low
            swing_high_price: float64 — price level of the swing high
            swing_low_price:  float64 — price level of the swing low
    """
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    swing_high_mask = np.zeros(n, dtype=bool)
    swing_low_mask = np.zeros(n, dtype=bool)
    swing_high_price = np.full(n, np.nan, dtype=np.float64)
    swing_low_price = np.full(n, np.nan, dtype=np.float64)

    for i in range(pivot_n, n - pivot_n):
        window_highs = highs[i - pivot_n: i + pivot_n + 1]
        window_lows = lows[i - pivot_n: i + pivot_n + 1]

        # Use tolerance for near-equal prices (fixes strict comparison issue)
        max_val = window_highs.max()
        min_val = window_lows.min()
        tol_high = max_val * (1 - price_tolerance) if price_tolerance else max_val
        tol_low = min_val * (1 + price_tolerance) if price_tolerance else min_val

        if highs[i] >= tol_high and np.argmax(window_highs) == pivot_n:
            swing_high_mask[i] = True
            swing_high_price[i] = highs[i]

        if lows[i] <= tol_low and np.argmin(window_lows) == pivot_n:
            swing_low_mask[i] = True
            swing_low_price[i] = lows[i]

    df = df.copy()
    df['swing_high'] = swing_high_mask
    df['swing_low'] = swing_low_mask
    df['swing_high_price'] = swing_high_price
    df['swing_low_price'] = swing_low_price
    return df


def build_swing_list(
    df: pd.DataFrame,
    pivot_n: int = 3
) -> list[dict]:
    """
    Build an ordered list of swing points from a DataFrame.

    Returns:
        List of dicts sorted by index:
        [{'type': 'high'|'low', 'price': float, 'index': int}, ...]
    """
    df = detect_swing_points_df(df, pivot_n)
    swings = []

    for i in df.index:
        if df.loc[i, 'swing_high']:
            swings.append({'type': 'high', 'price': float(df.loc[i, 'swing_high_price']), 'index': int(i)})
        if df.loc[i, 'swing_low']:
            swings.append({'type': 'low', 'price': float(df.loc[i, 'swing_low_price']), 'index': int(i)})

    return sorted(swings, key=lambda s: s['index'])


def determine_trend_from_swings(swings: list[dict]) -> str:
    """
    Determine prevailing trend from recent swing points.

    Returns: 'bullish', 'bearish', or 'neutral'

    Looks at the last 4 swing points. Requires at least 2 highs or 2 lows
    to establish direction.
    """
    if len(swings) < 4:
        return 'neutral'

    recent = swings[-4:]
    highs = [s for s in recent if s['type'] == 'high']
    lows = [s for s in recent if s['type'] == 'low']

    if len(highs) + len(lows) < 3:
        return 'neutral'

    higher_highs = highs[-1]['price'] > highs[-2]['price'] if len(highs) >= 2 else False
    higher_lows = lows[-1]['price'] > lows[-2]['price'] if len(lows) >= 2 else False
    lower_highs = highs[-1]['price'] < highs[-2]['price'] if len(highs) >= 2 else False
    lower_lows = lows[-1]['price'] < lows[-2]['price'] if len(lows) >= 2 else False

    has_hh = len(highs) >= 2 and higher_highs
    has_hl = len(lows) >= 2 and higher_lows
    has_lh = len(highs) >= 2 and lower_highs
    has_ll = len(lows) >= 2 and lower_lows

    if (has_hh and higher_lows) or (higher_highs and has_hl):
        return 'bullish'
    elif (has_lh and lower_lows) or (lower_highs and has_ll):
        return 'bearish'

    return 'neutral'
