"""
Market Structure Extraction Layer — Spatial State Module (Phase 1)

Extracts Fair Value Gaps (FVGs) and Order Blocks (OBs) from price action
into DataFrame columns following the Universal Zone Contract.

Universal Zone Contract (Base):
  {prefix}_active:     bool     — True while zone exists and is unmitigated
  {prefix}_upper:      float64  — Upper boundary price
  {prefix}_lower:      float64  — Lower boundary price
  {prefix}_created_at: datetime — Candle open_time when zone was formed

Extension columns per zone type:
  FVG:  {prefix}_volume — impulse candle volume
  OB:   {prefix}_volume, {prefix}_direction

CRITICAL DESIGN CHOICES:
  - Masked Forward-Filling: ffill for persistence, mitigation mask for death
  - Lookahead Bias Prevention: active flag shifted by +1
  - Single-Zone V1 Contract: only most recently formed unmitigated zone tracked
  - S/R zones do NOT use the kill-switch pattern (handled in sr_engine.py)
"""

import numpy as np
import pandas as pd
from typing import Optional

from app.core.indicators import compute_atr
from app.core.fractals import detect_swing_points_df, build_swing_list, determine_trend_from_swings


# ── FVG Extraction ──

def extract_fvgs(
    df: pd.DataFrame,
    mitigation_type: str = 'wick',
    lookback: int = 50,
) -> pd.DataFrame:
    """
    Extract Fair Value Gaps from price action.

    Returns the MOST RECENTLY FORMED unmitigated FVG only (V1 single-zone contract).
    If a new FVG forms while an older one is still active, the older one is
    dropped from tracking.

    Algorithm: For each 3-candle window (i-2, i-1, i):
      Bullish FVG: candle[i].low > candle[i-2].high
      Bearish FVG: candle[i].high < candle[i-2].low

    Args:
        df: DataFrame with columns [open, high, low, close, volume, open_time]
        mitigation_type: 'wick' (default) — high/low touches zone → mitigated
                         'body' — close enters zone → mitigated
        lookback: How many candles to scan backward from the end

    Returns:
        DataFrame with added columns:
            fvg_active:   bool
            fvg_upper:    float64
            fvg_lower:    float64
            fvg_volume:   float64
            fvg_created_at: datetime64
    """
    df = df.copy()
    n = len(df)

    # Initialize columns
    df['fvg_active'] = False
    df['fvg_upper'] = np.nan
    df['fvg_lower'] = np.nan
    df['fvg_volume'] = np.nan
    df['fvg_created_at'] = pd.NaT

    if n < 3:
        return df

    # Scan from the end backward within lookback window
    scan_start = max(0, n - lookback)

    for i in range(scan_start + 2, n):
        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]  # impulse candle
        c3 = df.iloc[i]

        # ── Bullish FVG ──
        if c3['low'] > c1['high']:
            fvg_upper_val = c3['low']
            fvg_lower_val = c1['high']
            fvg_volume_val = c2['volume']
            fvg_time_val = c3['open_time']

            # Check if already mitigated by any intervening candle
            already_mitigated = False
            for k in range(i + 1, n):
                if mitigation_type == 'wick':
                    if df.iloc[k]['low'] <= fvg_lower_val:
                        already_mitigated = True
                        break
                else:  # body
                    if df.iloc[k]['close'] <= fvg_lower_val:
                        already_mitigated = True
                        break

            if not already_mitigated:
                # Set zone at this candle, apply masked ffill + mitigation
                _apply_fvg_zone(df, i, fvg_upper_val, fvg_lower_val, fvg_volume_val, fvg_time_val,
                                mitigation_type)

        # ── Bearish FVG ──
        if c3['high'] < c1['low']:
            fvg_upper_val = c1['low']
            fvg_lower_val = c3['high']
            fvg_volume_val = c2['volume']
            fvg_time_val = c3['open_time']

            already_mitigated = False
            for k in range(i + 1, n):
                if mitigation_type == 'wick':
                    if df.iloc[k]['high'] >= fvg_upper_val:
                        already_mitigated = True
                        break
                else:  # body
                    if df.iloc[k]['close'] >= fvg_upper_val:
                        already_mitigated = True
                        break

            if not already_mitigated:
                _apply_fvg_zone(df, i, fvg_upper_val, fvg_lower_val, fvg_volume_val, fvg_time_val,
                                mitigation_type)

    return df


def _apply_fvg_zone(
    df: pd.DataFrame,
    formation_idx: int,
    upper_val: float,
    lower_val: float,
    volume_val: float,
    time_val,
    mitigation_type: str,
):
    """
    Apply a single FVG zone using masked forward-filling.

    Step 1: Set boundaries at formation candle (index i)
    Step 2: Forward-fill so zone persists across time
    Step 3: Shift active flag by +1 (lookahead bias defense)
    Step 4: Kill zone on mitigation
    Step 5: Recompute active from NaN state
    """
    n = len(df)

    # Overwrites any prior zone (single-zone V1 contract)
    # Step 1: Set at formation candle
    df.iloc[formation_idx, df.columns.get_loc('fvg_upper')] = upper_val
    df.iloc[formation_idx, df.columns.get_loc('fvg_lower')] = lower_val
    df.iloc[formation_idx, df.columns.get_loc('fvg_volume')] = volume_val
    df.iloc[formation_idx, df.columns.get_loc('fvg_created_at')] = time_val

    # Step 2: Forward-fill from formation onward
    fvg_upper_col = df.columns.get_loc('fvg_upper')
    fvg_lower_col = df.columns.get_loc('fvg_lower')
    fvg_volume_col = df.columns.get_loc('fvg_volume')
    fvg_created_col = df.columns.get_loc('fvg_created_at')

    for col_idx in [fvg_upper_col, fvg_lower_col, fvg_volume_col, fvg_created_col]:
        df.iloc[formation_idx:, col_idx] = df.iloc[formation_idx:, col_idx].ffill()

    # Step 3: Shift active flag by +1
    # Zone becomes active on candle AFTER formation (when confirming candle closes)
    active_start = formation_idx + 1
    if active_start < n:
        df.iloc[active_start:, df.columns.get_loc('fvg_active')] = df.iloc[
            formation_idx:, df.columns.get_loc('fvg_upper')
        ].notna().values[0]

    # Step 4: Mitigation kill switch
    for j in range(formation_idx + 1, n):
        row = df.iloc[j]
        upper = row['fvg_upper']
        lower = row['fvg_lower']

        if pd.isna(upper):
            continue

        if mitigation_type == 'wick':
            # Bullish FVG (upper > lower): low <= lower → mitigated
            # Bearish FVG (upper > lower but different meaning): high >= upper → mitigated
            # Distinguish by checking which side the gap is on
            if row['high'] >= upper:
                # Bearish FVG mitigated: price rises into the gap
                df.iloc[j, [fvg_upper_col, fvg_lower_col, fvg_volume_col]] = np.nan
                df.iloc[j, df.columns.get_loc('fvg_active')] = False
            elif row['low'] <= lower:
                # Bullish FVG mitigated: price drops into the gap
                df.iloc[j, [fvg_upper_col, fvg_lower_col, fvg_volume_col]] = np.nan
                df.iloc[j, df.columns.get_loc('fvg_active')] = False
        else:  # body
            if row['close'] >= upper or row['close'] <= lower:
                df.iloc[j, [fvg_upper_col, fvg_lower_col, fvg_volume_col]] = np.nan
                df.iloc[j, df.columns.get_loc('fvg_active')] = False

        # If mitigated, also NaN all subsequent rows (kill the zone entirely)
        if pd.isna(df.iloc[j, fvg_upper_col]):
            for k in range(j + 1, n):
                if not pd.isna(df.iloc[k, fvg_upper_col]):
                    df.iloc[k, [fvg_upper_col, fvg_lower_col, fvg_volume_col]] = np.nan
                    df.iloc[k, df.columns.get_loc('fvg_active')] = False
            break


# ── Order Block Extraction ──

def extract_order_blocks(
    df: pd.DataFrame,
    impulse_min: int = 2,
    impulse_max: int = 5,
    atr_displacement: float = 1.5,
    pivot_bars: int = 3,
) -> pd.DataFrame:
    """
    Extract Institutional Order Blocks from price action.

    A bullish OB is the last bearish candle before a significant bullish impulse.
    A bearish OB is the last bullish candle before a significant bearish impulse.

    Requirements:
      - Variable-length impulse (impulse_min to impulse_max consecutive candles)
      - ATR-normalized displacement >= atr_displacement
      - Break of Structure (impulse exceeds prior swing)

    Returns the MOST RECENTLY FORMED unmitigated OB only (V1 contract).

    Mitigation: body-close beyond the block boundary (institutional logic).
      Bullish OB mitigated when close < ob_lower
      Bearish OB mitigated when close > ob_upper

    Args:
        df: DataFrame with [open, high, low, close, volume, open_time]
        impulse_min: Minimum consecutive impulse candles
        impulse_max: Maximum consecutive impulse candles
        atr_displacement: Minimum ATR multiplier for impulse displacement
        pivot_bars: Bars for swing detection (BOS validation)

    Returns:
        DataFrame with added columns:
            ob_active:      bool
            ob_upper:       float64
            ob_lower:       float64
            ob_volume:      float64 — OB candle volume
            ob_direction:   str — 'bullish' or 'bearish'
            ob_created_at:  datetime64
    """
    df = df.copy()
    n = len(df)

    # Initialize columns
    df['ob_active'] = False
    df['ob_upper'] = np.nan
    df['ob_lower'] = np.nan
    df['ob_volume'] = np.nan
    df['ob_direction'] = None
    df['ob_created_at'] = pd.NaT

    if n < impulse_min + 2:
        return df

    # Compute ATR for displacement check
    atr_series = compute_atr(df['high'], df['low'], df['close'], 14)

    # Detect swing points for BOS validation
    df = detect_swing_points_df(df, pivot_bars)

    # Scan from the end backward
    scan_end = n - impulse_min - 1
    if scan_end < 1:
        return df

    for ob_idx in range(scan_end - 1, -1, -1):
        ob_candle = df.iloc[ob_idx]
        atr_val = atr_series.iloc[ob_idx]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        # ── Bullish OB candidate: bearish candle before bullish impulse ──
        if ob_candle['close'] < ob_candle['open']:  # bearish
            # Count consecutive bullish candles after OB
            impulse_candles = []
            for j in range(ob_idx + 1, min(ob_idx + 1 + impulse_max, n)):
                c = df.iloc[j]
                if c['close'] > c['open']:  # bullish
                    impulse_candles.append(c)
                else:
                    break

            if len(impulse_candles) < impulse_min:
                continue

            impulse_end_idx = ob_idx + len(impulse_candles)

            # ATR displacement check
            impulse_size = impulse_candles[-1]['close'] - impulse_candles[0]['open']
            if impulse_size < atr_val * atr_displacement:
                continue

            # BOS validation
            if not _has_bos(df, ob_idx, impulse_end_idx, 'bullish'):
                continue

            # Check if already mitigated
            ob_high = ob_candle['high']
            ob_low_val = ob_candle['low']
            already_mitigated = False
            for k in range(impulse_end_idx + 1, n):
                if df.iloc[k]['close'] < ob_low_val:
                    already_mitigated = True
                    break

            if already_mitigated:
                continue

            _apply_ob_zone(df, ob_idx, ob_high, ob_low_val, ob_candle['volume'],
                           ob_candle['open_time'], 'bullish')
            break  # Only track most recent (V1)

        # ── Bearish OB candidate: bullish candle before bearish impulse ──
        if ob_candle['close'] > ob_candle['open']:  # bullish
            impulse_candles = []
            for j in range(ob_idx + 1, min(ob_idx + 1 + impulse_max, n)):
                c = df.iloc[j]
                if c['close'] < c['open']:  # bearish
                    impulse_candles.append(c)
                else:
                    break

            if len(impulse_candles) < impulse_min:
                continue

            impulse_end_idx = ob_idx + len(impulse_candles)

            impulse_size = impulse_candles[0]['open'] - impulse_candles[-1]['close']
            if impulse_size < atr_val * atr_displacement:
                continue

            if not _has_bos(df, ob_idx, impulse_end_idx, 'bearish'):
                continue

            ob_high = ob_candle['high']
            ob_low_val = ob_candle['low']
            already_mitigated = False
            for k in range(impulse_end_idx + 1, n):
                if df.iloc[k]['close'] > ob_high:
                    already_mitigated = True
                    break

            if already_mitigated:
                continue

            _apply_ob_zone(df, ob_idx, ob_high, ob_low_val, ob_candle['volume'],
                           ob_candle['open_time'], 'bearish')
            break  # Only track most recent (V1)

    return df


def _has_bos(df: pd.DataFrame, ob_idx: int, impulse_end_idx: int, direction: str) -> bool:
    """
    Verify Break of Structure: the impulse breaks the prior swing point.

    Args:
        df: DataFrame with swing_high, swing_low columns
        ob_idx: Index of the OB candle
        impulse_end_idx: Last candle of the impulse
        direction: 'bullish' — impulse breaks prior high
                   'bearish' — impulse breaks prior low
    """
    # Find prior swing highs/lows before the OB
    prior_swing_highs = df.loc[:ob_idx - 1, 'swing_high_price'].dropna()
    prior_swing_lows = df.loc[:ob_idx - 1, 'swing_low_price'].dropna()

    # Impulse candles
    impulse_highs = df.loc[ob_idx + 1:impulse_end_idx, 'high']
    impulse_lows = df.loc[ob_idx + 1:impulse_end_idx, 'low']

    if direction == 'bullish':
        if prior_swing_highs.empty or impulse_highs.empty:
            return False
        return impulse_highs.max() > prior_swing_highs.max()
    else:
        if prior_swing_lows.empty or impulse_lows.empty:
            return False
        return impulse_lows.min() < prior_swing_lows.min()


def _apply_ob_zone(
    df: pd.DataFrame,
    formation_idx: int,
    upper_val: float,
    lower_val: float,
    volume_val: float,
    time_val,
    direction: str,
):
    """
    Apply a single OB zone using masked forward-filling.
    Same state machine pattern as FVG extraction.
    """
    n = len(df)
    ob_upper_col = df.columns.get_loc('ob_upper')
    ob_lower_col = df.columns.get_loc('ob_lower')
    ob_volume_col = df.columns.get_loc('ob_volume')
    ob_dir_col = df.columns.get_loc('ob_direction')
    ob_created_col = df.columns.get_loc('ob_created_at')
    ob_active_col = df.columns.get_loc('ob_active')

    # Step 1: Set at formation candle
    df.iloc[formation_idx, ob_upper_col] = upper_val
    df.iloc[formation_idx, ob_lower_col] = lower_val
    df.iloc[formation_idx, ob_volume_col] = volume_val
    df.iloc[formation_idx, ob_dir_col] = direction
    df.iloc[formation_idx, ob_created_col] = time_val

    # Step 2: Forward-fill
    for ci in [ob_upper_col, ob_lower_col, ob_volume_col, ob_created_col]:
        df.iloc[formation_idx:, ci] = df.iloc[formation_idx:, ci].ffill()

    # Step 3: Shift active flag by +1 (lookahead bias)
    active_start = formation_idx + 1
    if active_start < n:
        df.iloc[active_start:, ob_active_col] = True

    # For direction (string), ffill manually
    dir_vals = df.iloc[formation_idx:, ob_dir_col].ffill()
    df.iloc[formation_idx:, ob_dir_col] = dir_vals

    # Step 4: Mitigation kill switch (body-close for OBs)
    for j in range(formation_idx + 1, n):
        row = df.iloc[j]
        upper = row['ob_upper']
        lower = row['ob_lower']

        if pd.isna(upper):
            continue

        mitigated = False
        if direction == 'bullish':
            # Bullish OB dies when close drops below ob_lower
            if row['close'] < lower:
                mitigated = True
        else:
            # Bearish OB dies when close rises above ob_upper
            if row['close'] > upper:
                mitigated = True

        if mitigated:
            df.iloc[j, [ob_upper_col, ob_lower_col, ob_volume_col]] = np.nan
            df.iloc[j, ob_dir_col] = None
            df.iloc[j, ob_active_col] = False
            # Kill all subsequent rows
            for k in range(j + 1, n):
                if not pd.isna(df.iloc[k, ob_upper_col]):
                    df.iloc[k, [ob_upper_col, ob_lower_col, ob_volume_col]] = np.nan
                    df.iloc[k, ob_dir_col] = None
                    df.iloc[k, ob_active_col] = False
            break
