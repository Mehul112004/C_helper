"""
Temporal State Module — Event Detection (Phase 1)

Detects instantaneous triggers that happen on a single candle:
  - Change of Character (ChoCh) and Break of Structure (BOS)
  - Volume Climax
  - Liquidity Sweeps

CRITICAL: Events are NOT zones.
  - Events fire on a single candle and are boolean masks
  - _recent columns decay via rolling window, not forward-fill
  - Opposing events cancel each other's recent memory
"""

import numpy as np
import pandas as pd
from typing import Optional

from app.core.indicators import compute_volume_ma
from app.core.fractals import build_swing_list, determine_trend_from_swings


# ── ChoCh / BOS Detection ──

def detect_choch(
    df: pd.DataFrame,
    pivot_bars: int = 3,
    confirmation: str = 'body',
    recent_window: int = 10,
) -> pd.DataFrame:
    """
    Detect Change of Character (ChoCh) and Break of Structure (BOS) events.

    ChoCh = break of swing point against prevailing trend (reversal signal).
    BOS   = break of swing point in trend direction (continuation signal).

    Only body closes count (default) — wick-only piercings are rejected
    unless confirmation='wick'.

    Args:
        df: DataFrame with [open, high, low, close]
        pivot_bars: Bars on each side for swing detection
        confirmation: 'body' (default) — body close required
                      'wick' — any pierce counts
        recent_window: Rolling window size for _recent columns

    Returns:
        DataFrame with added columns:
            event_choch_bullish:         bool
            event_choch_bearish:         bool
            event_bos_bullish:           bool
            event_bos_bearish:           bool
            event_choch_bullish_recent:  bool — rolling(window).max(), opposing-cancelled
            event_choch_bearish_recent:  bool
            event_bos_bullish_recent:    bool
            event_bos_bearish_recent:    bool
    """
    df = df.copy()
    n = len(df)

    # Initialize event columns
    for col in ['event_choch_bullish', 'event_choch_bearish',
                'event_bos_bullish', 'event_bos_bearish',
                'event_choch_bullish_recent', 'event_choch_bearish_recent',
                'event_bos_bullish_recent', 'event_bos_bearish_recent']:
        df[col] = False

    if n < pivot_bars * 2 + 4:
        return df

    # Build swing map
    swings = build_swing_list(df, pivot_bars)
    if len(swings) < 4:
        return df

    # Process each candle where enough structure exists
    for i in range(pivot_bars * 2, n):
        # Get swings up to this candle (excluding future)
        visible_swings = [s for s in swings if s['index'] < i]
        if len(visible_swings) < 4:
            continue

        trend = determine_trend_from_swings(visible_swings)

        # Find most recent swing high and low before this candle
        last_swing_high = None
        last_swing_low = None
        for s in reversed(visible_swings):
            if s['type'] == 'high' and last_swing_high is None:
                last_swing_high = s
            if s['type'] == 'low' and last_swing_low is None:
                last_swing_low = s
            if last_swing_high and last_swing_low:
                break

        if last_swing_high is None or last_swing_low is None:
            continue

        row = df.iloc[i]
        body_high = max(row['open'], row['close'])
        body_low = min(row['open'], row['close'])

        if confirmation == 'body':
            broke_high = body_low > last_swing_high['price'] * 0.998
            broke_low = body_high < last_swing_low['price'] * 1.002
            wick_only_high = row['high'] > last_swing_high['price'] and body_high <= last_swing_high['price']
            wick_only_low = row['low'] < last_swing_low['price'] and body_low >= last_swing_low['price']
        else:  # wick
            broke_high = row['high'] > last_swing_high['price']
            broke_low = row['low'] < last_swing_low['price']
            wick_only_high = False
            wick_only_low = False

        # ── Bullish BOS: bull trend + body close above swing high ──
        if trend == 'bullish' and broke_high and not wick_only_high:
            df.iloc[i, df.columns.get_loc('event_bos_bullish')] = True

        # ── Bearish BOS: bear trend + body close below swing low ──
        if trend == 'bearish' and broke_low and not wick_only_low:
            df.iloc[i, df.columns.get_loc('event_bos_bearish')] = True

        # ── Bullish ChoCh: bear trend + body close above swing high ──
        if trend == 'bearish' and broke_high and not wick_only_high:
            df.iloc[i, df.columns.get_loc('event_choch_bullish')] = True

        # ── Bearish ChoCh: bull trend + body close below swing low ──
        if trend == 'bullish' and broke_low and not wick_only_low:
            df.iloc[i, df.columns.get_loc('event_choch_bearish')] = True

    # ── Compute _recent columns with opposing event cancellation ──
    _compute_recent_with_cancellation(df, 'event_choch_bullish', 'event_choch_bearish',
                                       'event_choch_bullish_recent', 'event_choch_bearish_recent',
                                       recent_window)
    _compute_recent_with_cancellation(df, 'event_bos_bullish', 'event_bos_bearish',
                                       'event_bos_bullish_recent', 'event_bos_bearish_recent',
                                       recent_window)

    return df


def _compute_recent_with_cancellation(
    df: pd.DataFrame,
    bull_col: str,
    bear_col: str,
    bull_recent_col: str,
    bear_recent_col: str,
    window: int,
):
    """
    Compute _recent columns where opposing events cancel each other.

    A bullish event is "recent" only if no bearish event occurred MORE RECENTLY
    within the rolling window.
    """
    n = len(df)
    bull_recent = np.zeros(n, dtype=bool)
    bear_recent = np.zeros(n, dtype=bool)

    for i in range(n):
        w_start = max(0, i - window + 1)
        w_end = i + 1

        bull_window = df.iloc[w_start:w_end][bull_col].values
        bear_window = df.iloc[w_start:w_end][bear_col].values

        # Find last True position in window (from the end)
        last_bull_pos = -1
        last_bear_pos = -1
        for j in range(len(bull_window) - 1, -1, -1):
            if bull_window[j] and last_bull_pos < 0:
                last_bull_pos = j
            if bear_window[j] and last_bear_pos < 0:
                last_bear_pos = j

        # Only recent if latest bull is more recent than latest bear
        if last_bull_pos >= 0 and last_bull_pos >= last_bear_pos:
            bull_recent[i] = True
        if last_bear_pos >= 0 and last_bear_pos >= last_bull_pos:
            bear_recent[i] = True

    df[bull_recent_col] = bull_recent
    df[bear_recent_col] = bear_recent


# ── Volume Climax Detection ──

def detect_volume_climax(
    df: pd.DataFrame,
    volume_ma_period: int = 20,
    threshold: float = 2.0,
    recent_window: int = 5,
) -> pd.DataFrame:
    """
    Detect Volume Climax events where volume spikes significantly.

    A volume climax occurs when volume exceeds threshold × volume_ma.

    Args:
        df: DataFrame with [open, close, volume]
        volume_ma_period: Period for volume moving average
        threshold: Volume multiplier to trigger climax
        recent_window: Rolling window for _recent column

    Returns:
        DataFrame with added columns:
            event_volume_climax:          bool
            event_volume_climax_bullish:  bool — climax + bullish close
            event_volume_climax_bearish:  bool — climax + bearish close
            event_volume_climax_recent:   bool — rolling(recent_window).max()
    """
    df = df.copy()

    # Compute volume MA
    volume_ma = compute_volume_ma(df['volume'], volume_ma_period)

    # Detect climax
    df['event_volume_climax'] = (df['volume'] > volume_ma * threshold) & volume_ma.notna()
    df['event_volume_climax_bullish'] = df['event_volume_climax'] & (df['close'] > df['open'])
    df['event_volume_climax_bearish'] = df['event_volume_climax'] & (df['close'] < df['open'])

    # Recent column — simple rolling max (no opposing cancellation needed)
    climax_vals = df['event_volume_climax'].astype(int).rolling(recent_window, min_periods=1).max()
    df['event_volume_climax_recent'] = climax_vals == 1

    return df


# ── Liquidity Sweep Detection ──

def detect_liquidity_sweep(
    df: pd.DataFrame,
    pivot_bars: int = 3,
    recent_window: int = 10,
) -> pd.DataFrame:
    """
    Detect liquidity sweep events (turtle soup / false breakout).

    Bullish sweep: wick pierces below swing low, then close recovers back above it.
    Bearish sweep: wick pierces above swing high, then close drops back below it.

    Args:
        df: DataFrame with [open, high, low, close]
        pivot_bars: Bars for swing detection
        recent_window: Rolling window for _recent column

    Returns:
        DataFrame with added columns:
            event_sweep_bullish:   bool
            event_sweep_bearish:   bool
            event_sweep_recent:    bool — rolling(recent_window).max()
    """
    df = df.copy()
    n = len(df)

    df['event_sweep_bullish'] = False
    df['event_sweep_bearish'] = False
    df['event_sweep_recent'] = False

    if n < pivot_bars * 2 + 2:
        return df

    swings = build_swing_list(df, pivot_bars)
    if len(swings) < 2:
        return df

    for i in range(pivot_bars * 2, n):
        visible_swings = [s for s in swings if s['index'] < i - 1]  # Not the same candle
        if len(visible_swings) < 2:
            continue

        last_swing_high = None
        last_swing_low = None
        for s in reversed(visible_swings):
            if s['type'] == 'high' and last_swing_high is None:
                last_swing_high = s
            if s['type'] == 'low' and last_swing_low is None:
                last_swing_low = s
            if last_swing_high and last_swing_low:
                break

        row = df.iloc[i]

        # Bullish sweep: wick below swing low, close back above
        if last_swing_low and row['low'] < last_swing_low['price'] and row['close'] > last_swing_low['price']:
            df.iloc[i, df.columns.get_loc('event_sweep_bullish')] = True

        # Bearish sweep: wick above swing high, close back below
        if last_swing_high and row['high'] > last_swing_high['price'] and row['close'] < last_swing_high['price']:
            df.iloc[i, df.columns.get_loc('event_sweep_bearish')] = True

    # Recent columns
    sweep_bull = df['event_sweep_bullish'].astype(int).rolling(recent_window, min_periods=1).max()
    sweep_bear = df['event_sweep_bearish'].astype(int).rolling(recent_window, min_periods=1).max()
    df['event_sweep_recent'] = ((sweep_bull == 1) | (sweep_bear == 1))

    return df
