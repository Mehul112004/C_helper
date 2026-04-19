"""
Indicator Computation Service
Computes and caches technical indicators from stored candle data.
Indicators: EMA (9, 21, 50, 100, 200), RSI (14), MACD (12/26/9),
            Bollinger Bands (20/2), ATR (14), Volume MA (20).
"""

import pandas as pd
import numpy as np
from datetime import datetime
import threading
from app.models.db import db, Candle
from app.core.config import CANDLE_WARMUP


class IndicatorService:
    """Computes and caches technical indicators from candle data."""

    # In-memory cache: key = (symbol, timeframe, last_open_time_iso) → result dict
    _cache_lock = threading.Lock()
    _cache: dict = {}

    # Minimum candles needed for the slowest indicator (EMA 200)
    MIN_CANDLES_IDEAL = CANDLE_WARMUP
    MIN_CANDLES_REQUIRED = 20  # Absolute minimum to compute anything useful

    # ---------- Static indicator computation methods ----------

    @staticmethod
    def compute_ema(closes: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return closes.ewm(span=period, adjust=False).mean()

    @staticmethod
    def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index using Wilder's smoothing method."""
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta.where(delta < 0, 0.0))

        # Use Wilder's smoothing (equivalent to EMA with alpha=1/period)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        with np.errstate(divide='ignore', invalid='ignore'):
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi = rsi.where(avg_loss != 0, other=100.0)  # pure uptrend → RSI 100
        return rsi

    @staticmethod
    def compute_macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
        """MACD Line, Signal Line, and Histogram."""
        ema_fast = closes.ewm(span=fast, adjust=False).mean()
        ema_slow = closes.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return {
            'macd_line': macd_line,
            'macd_signal': signal_line,
            'macd_histogram': histogram
        }

    @staticmethod
    def compute_bollinger(closes: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
        """Bollinger Bands: upper, middle (SMA), lower, and width."""
        middle = closes.rolling(window=period).mean()
        std = closes.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        # Width as a ratio of the middle band (normalized)
        width = (upper - lower) / middle
        return {
            'bb_upper': upper,
            'bb_middle': middle,
            'bb_lower': lower,
            'bb_width': width
        }

    @staticmethod
    def compute_atr(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
        """Average True Range."""
        prev_close = closes.shift(1)
        tr = pd.concat([
            highs - lows,
            (highs - prev_close).abs(),
            (lows - prev_close).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()

    @staticmethod
    def compute_keltner(
        highs: pd.Series, lows: pd.Series, closes: pd.Series,
        ema_period: int = 20, atr_period: int = 10, multiplier: float = 1.5,
    ) -> dict:
        """Keltner Channels: EMA ± (multiplier × ATR)."""
        ema = closes.ewm(span=ema_period, adjust=False).mean()
        atr = IndicatorService.compute_atr(highs, lows, closes, atr_period)
        upper = ema + (multiplier * atr)
        lower = ema - (multiplier * atr)
        return {'kc_upper': upper, 'kc_middle': ema, 'kc_lower': lower}

    @staticmethod
    def compute_volume_ma(volumes: pd.Series, period: int = 20) -> pd.Series:
        """Simple Moving Average of volume."""
        return volumes.rolling(window=period).mean()

    # ---------- Data fetching ----------

    @staticmethod
    def _fetch_candles_df(symbol: str, timeframe: str, limit: int = 250) -> pd.DataFrame:
        """
        Query the most recent `limit` candles from DB for the given symbol/timeframe.
        Returns a pandas DataFrame sorted by open_time ascending.
        """
        candles = (
            Candle.query
            .filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(Candle.open_time.desc())
            .limit(limit)
            .all()
        )

        if not candles:
            return pd.DataFrame()

        data = [c.to_dict() for c in candles]
        df = pd.DataFrame(data)
        df['open_time'] = pd.to_datetime(df['open_time'])
        df = df.sort_values('open_time').reset_index(drop=True)
        return df

    # ---------- Main computation entry point ----------

    @classmethod
    def compute_all(cls, symbol: str, timeframe: str, include_series: bool = False) -> dict:
        """
        Compute all indicators for a given symbol/timeframe.

        Returns a dict with:
        - 'latest': dict of the most recent indicator values
        - 'series': dict of full indicator series (if include_series=True)
        - 'warnings': list of warning messages (e.g. insufficient data)
        - 'candle_count': number of candles used
        - 'last_updated': ISO timestamp of the most recent candle
        """
        df = cls._fetch_candles_df(symbol, timeframe, limit=cls.MIN_CANDLES_IDEAL)
        candle_count = len(df)
        warnings = []

        # Check for insufficient data
        if candle_count == 0:
            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'latest': None,
                'series': None,
                'candle_count': 0,
                'last_updated': None,
                'warnings': [f'No candle data available for {symbol}/{timeframe}. Import data first.']
            }

        if candle_count < cls.MIN_CANDLES_IDEAL:
            warnings.append(
                f'Only {candle_count} candles available for {symbol}/{timeframe} — '
                f'indicators may be inaccurate (need ≥{cls.MIN_CANDLES_IDEAL} for EMA 200 warmup).'
            )

        last_open_time = df['open_time'].iloc[-1].isoformat()

        # Check cache
        cache_key = (symbol, timeframe, last_open_time)
        with cls._cache_lock:
            if cache_key in cls._cache:
                cached = cls._cache[cache_key]
                # Update series inclusion based on request
                if not include_series:
                    result = {**cached, 'series': None}
                else:
                    result = cached
                result['warnings'] = warnings
                return result

        # Compute all indicators
        closes = df['close']
        highs = df['high']
        lows = df['low']
        volumes = df['volume']

        ema_9 = cls.compute_ema(closes, 9)
        ema_21 = cls.compute_ema(closes, 21)
        ema_50 = cls.compute_ema(closes, 50)
        ema_100 = cls.compute_ema(closes, 100)
        ema_200 = cls.compute_ema(closes, 200)
        rsi_14 = cls.compute_rsi(closes, 14)
        macd = cls.compute_macd(closes, 12, 26, 9)
        bb = cls.compute_bollinger(closes, 20, 2.0)
        kc = cls.compute_keltner(highs, lows, closes, 20, 10, 1.5)
        atr_14 = cls.compute_atr(highs, lows, closes, 14)
        vol_ma_20 = cls.compute_volume_ma(volumes, 20)

        # Extract latest values (last row, replacing NaN with None)
        def _safe_last(series: pd.Series):
            val = series.iloc[-1]
            if pd.isna(val):
                return None
            return round(float(val), 6)

        latest = {
            'ema_9': _safe_last(ema_9),
            'ema_21': _safe_last(ema_21),
            'ema_50': _safe_last(ema_50),
            'ema_100': _safe_last(ema_100),
            'ema_200': _safe_last(ema_200),
            'rsi_14': _safe_last(rsi_14),
            'macd_line': _safe_last(macd['macd_line']),
            'macd_signal': _safe_last(macd['macd_signal']),
            'macd_histogram': _safe_last(macd['macd_histogram']),
            'bb_upper': _safe_last(bb['bb_upper']),
            'bb_middle': _safe_last(bb['bb_middle']),
            'bb_lower': _safe_last(bb['bb_lower']),
            'bb_width': _safe_last(bb['bb_width']),
            'kc_upper': _safe_last(kc['kc_upper']),
            'kc_lower': _safe_last(kc['kc_lower']),
            'atr_14': _safe_last(atr_14),
            'volume_ma_20': _safe_last(vol_ma_20),
        }

        # Build series data (timestamps + values) for charting
        timestamps = df['open_time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ').tolist()

        def _series_to_list(series: pd.Series) -> list:
            """Convert a pandas Series to a list of {time, value} dicts, preserving index alignment."""
            result = []
            for i, val in enumerate(series):
                if pd.notna(val):
                    result.append({'time': timestamps[i], 'value': round(float(val), 6)})
                else:
                    result.append({'time': timestamps[i], 'value': None})
            return result

        series_data = {
            'ema_9': _series_to_list(ema_9),
            'ema_21': _series_to_list(ema_21),
            'ema_50': _series_to_list(ema_50),
            'ema_100': _series_to_list(ema_100),
            'ema_200': _series_to_list(ema_200),
            'rsi_14': _series_to_list(rsi_14),
            'macd_line': _series_to_list(macd['macd_line']),
            'macd_signal': _series_to_list(macd['macd_signal']),
            'macd_histogram': _series_to_list(macd['macd_histogram']),
            'bb_upper': _series_to_list(bb['bb_upper']),
            'bb_middle': _series_to_list(bb['bb_middle']),
            'bb_lower': _series_to_list(bb['bb_lower']),
            'bb_width': _series_to_list(bb['bb_width']),
            'kc_upper': _series_to_list(kc['kc_upper']),
            'kc_lower': _series_to_list(kc['kc_lower']),
            'atr_14': _series_to_list(atr_14),
            'volume_ma_20': _series_to_list(vol_ma_20),
        }

        result = {
            'symbol': symbol,
            'timeframe': timeframe,
            'latest': latest,
            'series': series_data,
            'candle_count': candle_count,
            'last_updated': last_open_time,
            'warnings': warnings,
        }

        # Cache the full result (with series)
        with cls._cache_lock:
            cls._cache[cache_key] = result

        # Return without series if not requested
        if not include_series:
            return {**result, 'series': None}

        return result

    @classmethod
    def invalidate_cache(cls, symbol: str = None, timeframe: str = None):
        """
        Invalidate cached indicator results.
        If symbol/timeframe provided, only invalidate matching entries.
        If neither provided, clear entire cache.
        """
        with cls._cache_lock:
            if symbol is None and timeframe is None:
                cls._cache.clear()
                return

            keys_to_remove = [
                k for k in cls._cache
                if (symbol is None or k[0] == symbol) and (timeframe is None or k[1] == timeframe)
            ]
            for k in keys_to_remove:
                cls._cache.pop(k, None)
