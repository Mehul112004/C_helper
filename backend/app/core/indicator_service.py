"""
Indicator Service (Caching Wrapper)
Wraps the pure stateless indicator functions from app.core.indicators
with DB fetching, caching, and API-friendly serialization.

This is the service layer that API blueprints and the live scanner call.
The extraction layer (app.core.indicators) exposes pure functions only.
"""

import pandas as pd
import threading
from datetime import datetime
from typing import Optional

from app.models.db import db, Candle
from app.core.config import CANDLE_WARMUP
from app.core.indicators import (
    compute_ema,
    compute_rsi,
    compute_macd,
    compute_bollinger,
    compute_atr,
    compute_keltner,
    compute_volume_ma,
)


class IndicatorService:
    """Computes, caches, and serves technical indicators from candle data."""

    # ── Static methods delegating to pure extraction functions ──
    # These exist for backward compatibility. New code should import
    # pure functions directly from app.core.indicators.

    @staticmethod
    def compute_ema(closes, period):
        return compute_ema(closes, period)

    @staticmethod
    def compute_rsi(closes, period=14):
        return compute_rsi(closes, period)

    @staticmethod
    def compute_macd(closes, fast=12, slow=26, signal=9):
        return compute_macd(closes, fast, slow, signal)

    @staticmethod
    def compute_bollinger(closes, period=20, std_dev=2.0):
        return compute_bollinger(closes, period, std_dev)

    @staticmethod
    def compute_atr(highs, lows, closes, period=14):
        return compute_atr(highs, lows, closes, period)

    @staticmethod
    def compute_keltner(highs, lows, closes, ema_period=20, atr_period=10, multiplier=1.5):
        return compute_keltner(highs, lows, closes, ema_period, atr_period, multiplier)

    @staticmethod
    def compute_volume_ma(volumes, period=20):
        return compute_volume_ma(volumes, period)

    # ── Caching and DB fetch ──

    _cache_lock = threading.Lock()
    _cache: dict = {}

    MIN_CANDLES_IDEAL = CANDLE_WARMUP
    MIN_CANDLES_REQUIRED = 20

    @staticmethod
    def _fetch_candles_df(symbol: str, timeframe: str, limit: int = 250) -> pd.DataFrame:
        """Query the most recent `limit` candles from DB, sorted ascending."""
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

    @classmethod
    def compute_all(cls, symbol: str, timeframe: str, include_series: bool = False) -> dict:
        """
        Compute all indicators for a given symbol/timeframe.

        Returns a dict with 'latest', 'series', 'warnings', 'candle_count',
        and 'last_updated'.
        """
        df = cls._fetch_candles_df(symbol, timeframe, limit=cls.MIN_CANDLES_IDEAL)
        candle_count = len(df)
        warnings = []

        if candle_count == 0:
            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'latest': None,
                'series': None,
                'candle_count': 0,
                'last_updated': None,
                'warnings': [f'No candle data available for {symbol}/{timeframe}. Import data first.'],
            }

        if candle_count < cls.MIN_CANDLES_IDEAL:
            warnings.append(
                f'Only {candle_count} candles available for {symbol}/{timeframe} — '
                f'indicators may be inaccurate (need ≥{cls.MIN_CANDLES_IDEAL} for EMA 200 warmup).'
            )

        last_open_time = df['open_time'].iloc[-1].isoformat()

        cache_key = (symbol, timeframe, last_open_time)
        with cls._cache_lock:
            if cache_key in cls._cache:
                cached = cls._cache[cache_key]
                result = {**cached, 'series': cached['series'] if include_series else None}
                result['warnings'] = warnings
                return result

        closes = df['close']
        highs = df['high']
        lows = df['low']
        volumes = df['volume']

        ema_9 = compute_ema(closes, 9)
        ema_21 = compute_ema(closes, 21)
        ema_50 = compute_ema(closes, 50)
        ema_100 = compute_ema(closes, 100)
        ema_200 = compute_ema(closes, 200)
        rsi_14 = compute_rsi(closes, 14)
        macd = compute_macd(closes, 12, 26, 9)
        bb = compute_bollinger(closes, 20, 2.0)
        kc = compute_keltner(highs, lows, closes, 20, 10, 1.5)
        atr_14 = compute_atr(highs, lows, closes, 14)
        vol_ma_20 = compute_volume_ma(volumes, 20)

        def _safe_last(series: pd.Series) -> Optional[float]:
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

        timestamps = df['open_time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ').tolist()

        def _series_to_list(series: pd.Series) -> list:
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

        with cls._cache_lock:
            cls._cache[cache_key] = result

        if not include_series:
            return {**result, 'series': None}

        return result

    @classmethod
    def invalidate_cache(cls, symbol: str = None, timeframe: str = None):
        """Invalidate cached indicator results. Scoped or full clear."""
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
