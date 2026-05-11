"""
Market Regime Detection Module

Determines the current market state (trending/ranging, volatility regime, structural bias)
and adds regime columns to DataFrames so strategies can gate themselves by market context.

Regime definitions:
  - TRENDING_UP:   ADX >= 25, EMAs stacked bullishly, HH + HL structure
  - TRENDING_DOWN: ADX >= 25, EMAs stacked bearishly, LH + LL structure
  - RANGING:       ADX < 20 or no clear structure
  - CHOPPY:        ADX 20-25, mixed signals

Volatility regime:
  - LOW:     BB width < 20-period average
  - NORMAL:  BB width within 1 std of average
  - HIGH:    BB width > 1 std above average
"""

import numpy as np
import pandas as pd


def detect_market_regime(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add market regime columns to the DataFrame.

    Required columns: close, high, low, ema_50, ema_100, ema_200, adx, bb_width
    (All must be computed beforehand via pre_process)

    Adds:
      regime:           str — 'TRENDING_UP', 'TRENDING_DOWN', 'RANGING', 'CHOPPY'
      regime_strength:  float — 0.0 to 1.0, how strong the regime signal is
      volatility_regime: str — 'LOW', 'NORMAL', 'HIGH'
      structural_bias:  str — 'BULLISH', 'BEARISH', 'NEUTRAL'
    """
    df = df.copy()
    n = len(df)

    df['regime'] = 'RANGING'
    df['regime_strength'] = 0.0
    df['volatility_regime'] = 'NORMAL'
    df['structural_bias'] = 'NEUTRAL'

    if n < 30:
        return df

    # ── ADX-based trend strength ──
    adx_ok = df['adx'].notna() & (df['adx'] >= 20)
    strong_trend = df['adx'].notna() & (df['adx'] >= 25)

    # ── EMA stack alignment ──
    emas_ok = (
        df['ema_50'].notna() & df['ema_100'].notna() & df['ema_200'].notna()
    )
    bullish_stack = emas_ok & (df['ema_50'] > df['ema_100']) & (df['ema_100'] > df['ema_200'])
    bearish_stack = emas_ok & (df['ema_50'] < df['ema_100']) & (df['ema_100'] < df['ema_200'])

    # ── Price vs EMAs ──
    price_above_50 = df['close'] > df['ema_50']
    price_below_50 = df['close'] < df['ema_50']

    # ── Classify regime ──
    # Strong bull trend: ADX >= 25, bullish EMA stack, price above EMA50
    bull_regime = strong_trend & bullish_stack & price_above_50
    # Strong bear trend: ADX >= 25, bearish EMA stack, price below EMA50
    bear_regime = strong_trend & bearish_stack & price_below_50
    # Weak bull: ADX 20-25 or missing EMA confirmation
    weak_bull = adx_ok & ~bull_regime & ~bear_regime & price_above_50 & bullish_stack
    # Weak bear
    weak_bear = adx_ok & ~bull_regime & ~bear_regime & price_below_50 & bearish_stack
    # Choppy: ADX 20-25 with no clear EMA alignment
    choppy = adx_ok & ~bull_regime & ~bear_regime & ~weak_bull & ~weak_bear

    df.loc[bull_regime, 'regime'] = 'TRENDING_UP'
    df.loc[weak_bull, 'regime'] = 'TRENDING_UP'
    df.loc[bear_regime, 'regime'] = 'TRENDING_DOWN'
    df.loc[weak_bear, 'regime'] = 'TRENDING_DOWN'
    df.loc[choppy, 'regime'] = 'CHOPPY'

    # ── Regime strength (0-1) ──
    # Based on ADX normalized + EMA stack conviction
    adx_norm = df['adx'].clip(0, 50) / 50.0  # ADX capped at 50
    df['regime_strength'] = np.where(
        df['regime'].isin(['TRENDING_UP', 'TRENDING_DOWN']),
        (adx_norm * 0.6 + 0.4).clip(0, 1),  # Base 0.4 + ADX contribution
        0.2  # Low strength for ranging/choppy
    )

    # ── Volatility regime (BB width based) ──
    if 'bb_width' in df.columns and df['bb_width'].notna().sum() >= 20:
        bb_mean = df['bb_width'].rolling(20).mean()
        bb_std = df['bb_width'].rolling(20).std().fillna(0)
        df['volatility_regime'] = np.where(
            df['bb_width'].notna() & bb_mean.notna(),
            np.where(
                df['bb_width'] > bb_mean + bb_std, 'HIGH',
                np.where(df['bb_width'] < bb_mean - bb_std, 'LOW', 'NORMAL')
            ),
            'NORMAL'
        )

    # ── Structural bias (from price vs EMAs) ──
    df.loc[bullish_stack & price_above_50, 'structural_bias'] = 'BULLISH'
    df.loc[bearish_stack & price_below_50, 'structural_bias'] = 'BEARISH'

    return df


def is_trending(df: pd.DataFrame, idx: int = -1) -> bool:
    """Check if the current bar is in a trending regime."""
    if 'regime' not in df.columns:
        return False
    regime = df.iloc[idx].get('regime', 'RANGING')
    return regime in ('TRENDING_UP', 'TRENDING_DOWN')


def is_ranging(df: pd.DataFrame, idx: int = -1) -> bool:
    """Check if the current bar is in a ranging regime."""
    if 'regime' not in df.columns:
        return False
    return df.iloc[idx].get('regime', 'RANGING') in ('RANGING', 'CHOPPY')


def get_trend_direction(df: pd.DataFrame, idx: int = -1) -> str:
    """Get the trend direction ('UP', 'DOWN', 'NEUTRAL') for the current bar."""
    if 'regime' not in df.columns:
        return 'NEUTRAL'
    regime = df.iloc[idx].get('regime', 'RANGING')
    if regime == 'TRENDING_UP':
        return 'UP'
    if regime == 'TRENDING_DOWN':
        return 'DOWN'
    return 'NEUTRAL'
