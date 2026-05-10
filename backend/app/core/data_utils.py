"""
Data fetching utilities for the extraction layer.

Provides time-agnostic finalized candle fetching with staleness guards
for both live and backtest modes.
"""

import pandas as pd
from datetime import datetime, timezone
from typing import Optional

from app.models.db import db, Candle


# Timeframe → duration in milliseconds
TIMEFRAME_MS = {
    '1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000,
    '30m': 1_800_000, '1h': 3_600_000, '2h': 7_200_000,
    '4h': 14_400_000, '6h': 21_600_000, '8h': 28_800_000,
    '12h': 43_200_000, '1d': 86_400_000, '3d': 259_200_000,
    '1w': 604_800_000,
}


class StaleDataError(Exception):
    """Raised when finalized candles are too old to be reliable."""


def get_finalized_candles(
    symbol: str,
    timeframe: str,
    limit: int = 500,
    as_of_ms: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    Returns ONLY closed candles. Time-agnostic — callers inject the reference time.

    Two query modes:
      - Live mode:  `get_finalized_candles(symbol, tf, limit=500)`
                    Uses wall-clock utcnow() for staleness + open-candle filtering.
      - Backtest:   `get_finalized_candles(symbol, tf, start_date=..., end_date=...)`
                    Uses simulated time for all checks. Staleness guard is DISABLED
                    in date-range mode because the "last candle" is the end of the
                    simulation window, not a live market condition.

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe (e.g., '1h')
        limit: Max candles to return (live mode only)
        as_of_ms: Reference timestamp in ms. Live scanner passes utcnow();
                  backtester passes end_date_ms. Defaults to utcnow().
        start_date: If provided, query by date range instead of limit (backtest mode)
        end_date: Required if start_date is provided

    Guards (live mode only):
    1. Drops unclosed candles (evolving candle)
    2. Raises StaleDataError if the most recent closed candle is older than
       2x the timeframe duration

    Guards (both modes):
    1. Drops rows where open_time + timeframe_duration > as_of_ms
       (these candles have not yet closed from the reference time's perspective)
    """
    tf_ms = TIMEFRAME_MS.get(timeframe)
    if tf_ms is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    # Resolve the reference time: caller-injected or wall clock
    if as_of_ms is not None:
        now_ms = as_of_ms
    else:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Determine query mode
    is_backtest = start_date is not None and end_date is not None

    if is_backtest:
        candles = (
            Candle.query
            .filter_by(symbol=symbol, timeframe=timeframe)
            .filter(Candle.open_time >= start_date)
            .filter(Candle.open_time <= end_date)
            .order_by(Candle.open_time.asc())
            .all()
        )
    else:
        candles = (
            Candle.query
            .filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(Candle.open_time.desc())
            .limit(limit + 1)
            .all()
        )
        # Reverse to ascending for proper time ordering
        candles = list(reversed(candles))

    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame([c.to_dict() for c in candles])

    # Guard: Drop unclosed candles (relative to as_of_ms, not wall clock)
    df['open_time'] = pd.to_datetime(df['open_time'])
    df['open_time_ms'] = df['open_time'].astype('int64') // 10**6
    df = df[df['open_time_ms'] + tf_ms <= now_ms]
    df = df.sort_values('open_time').reset_index(drop=True)

    # Staleness guard: LIVE MODE ONLY
    if not is_backtest and len(df) > 0:
        last_candle_time_ms = df['open_time_ms'].iloc[-1]
        age_ms = now_ms - last_candle_time_ms
        max_age_ms = tf_ms * 2
        if age_ms > max_age_ms:
            raise StaleDataError(
                f"Most recent closed candle for {symbol} {timeframe} is "
                f"{age_ms / 1000:.0f}s old (max allowed: {max_age_ms / 1000:.0f}s). "
                f"WebSocket may be disconnected or gap-healer failed."
            )

    return df
