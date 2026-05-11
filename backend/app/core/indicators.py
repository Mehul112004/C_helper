"""
Indicator Extraction Layer — Pure Stateless Functions

Phase 1 refactor: No caching, no DB access, no side effects.
Every function is a pure mathematical transform from pd.Series to pd.Series.

Contract:
  - Input: One or more pd.Series of price data (any length)
  - Output: pd.Series of same index, float64
  - NaN policy: Early values are NaN (insufficient warm-up). Consumers
    must guard with .isna() or .notna() before using in boolean conditions.
  - No side effects: Does not mutate input, does not modify any DataFrame.
"""

import numpy as np
import pandas as pd

# Minimum candles required per indicator
MIN_CANDLES = {
    'ema': 2,          # at least span for any meaningful ewm
    'rsi': 15,         # period + 1
    'macd': 35,        # slow + signal
    'bollinger': 20,   # rolling window
    'atr': 15,         # period + 1
    'keltner': 20,     # ema_period
    'volume_ma': 20,   # rolling window
}


def compute_ema(closes: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average.

    Contract:
      Input:  pd.Series of close prices
      Output: pd.Series of same index, float64
      NaN:    First (period - 1) values are NaN (insufficient warm-up).
              These are EXPECTED and must be guarded by consumers.
    """
    return closes.ewm(span=period, adjust=False).mean()


def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index using Wilder's smoothing method.

    Contract:
      Input:  pd.Series of close prices
      Output: pd.Series of same index, float64, range [0, 100]
      NaN:    First `period` values are NaN (insufficient warm-up).
    """
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    with np.errstate(divide='ignore', invalid='ignore'):
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0, other=100.0)
    return rsi


def compute_macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """
    MACD Line, Signal Line, and Histogram.

    Contract:
      Input:  pd.Series of close prices
      Output: dict with keys 'macd_line', 'macd_signal', 'macd_histogram'
              each a pd.Series of same index
      NaN:    First `slow + signal` values are NaN.
    """
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {'macd_line': macd_line, 'macd_signal': signal_line, 'macd_histogram': histogram}


def compute_bollinger(closes: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
    """
    Bollinger Bands: upper, middle (SMA), lower, and normalized width.

    Contract:
      Input:  pd.Series of close prices
      Output: dict with keys 'bb_upper', 'bb_middle', 'bb_lower', 'bb_width'
      NaN:    First `period - 1` values are NaN.
    """
    middle = closes.rolling(window=period).mean()
    std = closes.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    width = (upper - lower) / middle
    return {'bb_upper': upper, 'bb_middle': middle, 'bb_lower': lower, 'bb_width': width}


def compute_atr(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
    """
    Average True Range.

    Contract:
      Input:  Three pd.Series of same index
      Output: pd.Series of same index, float64
      NaN:    First `period` values are NaN.
    """
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def compute_keltner(
    highs: pd.Series, lows: pd.Series, closes: pd.Series,
    ema_period: int = 20, atr_period: int = 10, multiplier: float = 1.5,
) -> dict:
    """
    Keltner Channels: EMA ± (multiplier × ATR).

    Contract:
      Input:  Three pd.Series of same index
      Output: dict with keys 'kc_upper', 'kc_middle', 'kc_lower'
      NaN:    First `ema_period` values are NaN.
    """
    ema = closes.ewm(span=ema_period, adjust=False).mean()
    atr = compute_atr(highs, lows, closes, atr_period)
    upper = ema + (multiplier * atr)
    lower = ema - (multiplier * atr)
    return {'kc_upper': upper, 'kc_middle': ema, 'kc_lower': lower}


def compute_adx(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
    """
    Average Directional Index (ADX) — trend strength indicator.

    Contract:
      Input:  Three pd.Series of same index
      Output: pd.Series of same index, float64, range [0, 100]
      NaN:    First 2*period values are NaN.
    """
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    up_move = highs - highs.shift(1)
    down_move = lows.shift(1) - lows
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=highs.index).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    minus_dm = pd.Series(minus_dm, index=lows.index).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    with np.errstate(divide='ignore', invalid='ignore'):
        plus_di = 100.0 * plus_dm / atr
        minus_di = 100.0 * minus_dm / atr
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = pd.Series(dx, index=highs.index).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    adx = adx.where(atr > 0, np.nan)
    return adx


def compute_volume_ma(volumes: pd.Series, period: int = 20) -> pd.Series:
    """
    Simple Moving Average of volume.

    Contract:
      Input:  pd.Series of volume values
      Output: pd.Series of same index, float64
      NaN:    First `period - 1` values are NaN.
    """
    return volumes.rolling(window=period).mean()
