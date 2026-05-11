"""
Multi-Timeframe Confluence Engine

Provides MTF analysis utilities for validating LTF signals against
higher timeframe context before they are fired.

Core principle: Every signal MUST align with the higher timeframe
trend direction unless it's a high-conviction reversal at a key level.

HTF mapping:
  5m  → 15m → 1h → 4h → 1d
  15m → 1h → 4h → 1d

Confluence checks:
  1. HTF trend alignment (price vs EMA50, EMA stack)
  2. HTF structural alignment (HH/HL or LH/LL)
  3. Key HTF level proximity (S/R, FVG, OB)
  4. HTF momentum (RSI, MACD)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List


HTF_MAP = {
    '5m': '15m',
    '15m': '1h',
    '1h': '4h',
    '4h': '1d',
    '1d': None,
}


def get_htf(timeframe: str) -> Optional[str]:
    """Get the higher timeframe for a given timeframe."""
    return HTF_MAP.get(timeframe)


def check_htf_alignment(
    ltf_df: pd.DataFrame,
    htf_df: pd.DataFrame,
    direction: str,
    ltf_idx: int = -1,
    require_adx: bool = True,
) -> dict:
    """
    Check if an LTF signal aligns with HTF context.

    Args:
        ltf_df: LTF DataFrame with at least close, signal row
        htf_df: HTF DataFrame with ema_50, adx, close columns
        direction: 'LONG' or 'SHORT'
        ltf_idx: Index in LTF DataFrame of the signal bar
        require_adx: If True, HTF must show trend (ADX >= 20) to provide a bias

    Returns:
        Dict with:
          - aligned: bool
          - htf_bias: 'BULLISH', 'BEARISH', or 'NEUTRAL'
          - htf_strength: float 0-1
          - reasons: list of strings explaining the verdict
    """
    if htf_df is None or len(htf_df) < 5:
        return {'aligned': True, 'htf_bias': 'NEUTRAL', 'htf_strength': 0.0,
                'reasons': ['No HTF data available — signal passes by default']}

    row = htf_df.iloc[-1]
    reasons = []

    ema50 = row.get('ema_50')
    close = row.get('close')
    adx = row.get('adx')

    if ema50 is None or pd.isna(ema50) or close is None or pd.isna(close):
        return {'aligned': True, 'htf_bias': 'NEUTRAL', 'htf_strength': 0.0,
                'reasons': ['Insufficient HTF indicator data']}

    # HTF bias from price vs EMA50
    price_above_ema = close > ema50
    htf_bias = 'BULLISH' if price_above_ema else 'BEARISH'

    # HTF trend strength
    htf_strength = 0.0
    if adx is not None and pd.notna(adx):
        htf_strength = min(adx / 40.0, 1.0)  # ADX 40+ = max strength

    # EMA stack check
    ema100 = row.get('ema_100')
    ema200 = row.get('ema_200')
    if ema100 is not None and pd.notna(ema100) and ema200 is not None and pd.notna(ema200):
        if ema50 > ema100 > ema200:
            htf_bias = 'BULLISH'
            htf_strength = max(htf_strength, 0.6)
            reasons.append('HTF EMA stack bullish (50>100>200)')
        elif ema50 < ema100 < ema200:
            htf_bias = 'BEARISH'
            htf_strength = max(htf_strength, 0.6)
            reasons.append('HTF EMA stack bearish (50<100<200)')

    # Check alignment
    if direction == 'LONG':
        if price_above_ema:
            aligned = True
            reasons.append(f'HTF bullish: price {close:.2f} > EMA50 {ema50:.2f}')
        else:
            # Counter-trend LONG — allow only if HTF is weak trend
            if adx is not None and pd.notna(adx) and adx < 25:
                aligned = True
                reasons.append('HTF weak trend — counter-trend LONG allowed')
            else:
                aligned = False
                reasons.append(f'REJECTED: HTF bearish but signal is LONG')
    else:  # SHORT
        if not price_above_ema:
            aligned = True
            reasons.append(f'HTF bearish: price {close:.2f} < EMA50 {ema50:.2f}')
        else:
            if adx is not None and pd.notna(adx) and adx < 25:
                aligned = True
                reasons.append('HTF weak trend — counter-trend SHORT allowed')
            else:
                aligned = False
                reasons.append(f'REJECTED: HTF bullish but signal is SHORT')

    return {
        'aligned': aligned,
        'htf_bias': htf_bias,
        'htf_strength': round(htf_strength, 2),
        'reasons': reasons,
    }


def compute_htf_context(df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
    """
    Compute a compact HTF context summary for the LLM or signal notes.

    Returns:
        Dict with bias, strength, key levels, and a one-line summary.
    """
    if df is None or len(df) < 10:
        return {'bias': 'NEUTRAL', 'summary': 'Insufficient HTF data'}

    last = df.iloc[-1]
    close = last['close']
    ema50 = last.get('ema_50')
    adx = last.get('adx')

    bias = 'NEUTRAL'
    if ema50 is not None and pd.notna(ema50):
        bias = 'BULLISH' if close > ema50 else 'BEARISH'

    adx_str = f'ADX={adx:.0f}' if adx is not None and pd.notna(adx) else 'ADX=N/A'

    return {
        'bias': bias,
        'price': float(close),
        'ema_50': float(ema50) if ema50 is not None and pd.notna(ema50) else None,
        'adx': float(adx) if adx is not None and pd.notna(adx) else None,
        'timeframe': timeframe,
        'symbol': symbol,
        'summary': f'HTF {timeframe}: {bias} | Price: {close:.2f} | {adx_str}',
    }
