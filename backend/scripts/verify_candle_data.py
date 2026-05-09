"""
Candle Data Integrity Verifier

Cross-checks every candle stored in the local DB against Binance's
official kline REST API. Detects:
  - Missing candles (Binance has them, DB doesn't)
  - Corrupted OHLCV values (DB open/high/low/close/volume differ)
  - Extra/stale candles (DB has them, Binance doesn't — stale data)

Usage:
    python scripts/verify_candle_data.py
    python scripts/verify_candle_data.py --symbol BTCUSDT
    python scripts/verify_candle_data.py --symbol BTCUSDT --timeframe 1h --days 7
    python scripts/verify_candle_data.py --fix     # repair corrupted candles

Output:
    A report printed to stdout summarising:
      - total candles checked
      - mismatched (corrupted)
      - missing (gap)
      - extra (stale)
      - per-timeframe breakdown
"""

import sys
import os
import argparse
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# Patch path so 'app' is discoverable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.models.db import db, Candle as CandleModel
from app.utils.binance import fetch_klines


def _binance_to_datetime(ms_timestamp: int) -> datetime:
    """Convert Binance millisecond timestamp to timezone-aware UTC datetime."""
    return datetime.fromtimestamp(ms_timestamp / 1000.0, tz=timezone.utc)


def _datetime_to_binance_ms(dt: datetime) -> int:
    """Convert timezone-aware datetime to Binance millisecond timestamp."""
    return int(dt.timestamp() * 1000)


def _get_timeframe_ms(tf: str) -> int:
    """Convert a timeframe string like '1h', '15m', '4h', '1d' to milliseconds."""
    unit = tf[-1].lower()
    val = int(tf[:-1])
    if unit == 'm':
        return val * 60 * 1000
    elif unit == 'h':
        return val * 3600 * 1000
    elif unit == 'd':
        return val * 86400 * 1000
    elif unit == 'w':
        return val * 7 * 86400 * 1000
    else:
        raise ValueError(f"Unknown timeframe unit: {tf}")


def _float_close(a: float, b: float, rel_tol: float = 1e-10) -> bool:
    """Check if two floats are equal within relative tolerance."""
    if a == b:
        return True
    return math.isclose(a, b, rel_tol=rel_tol)


def _build_binance_index(binance_candles: list[dict]) -> dict:
    """
    Build a lookup index keyed by the exact open_time (as datetime)
    for O(1) comparison lookups.
    """
    index = {}
    for c in binance_candles:
        key = c['open_time']
        if isinstance(key, int):
            key = _binance_to_datetime(key)
        index[key] = c
    return index


def verify_symbol(
    symbol: str,
    timeframes: list[str] = None,
    lookback_days: int = 30,
    fix: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Verify candle data for a single symbol across one or more timeframes.

    Must be called from within a Flask app context.
    Returns a summary dict with per-timeframe stats.
    """
    # Determine which timeframes to check
    if timeframes is None:
        rows = db.session.query(CandleModel.timeframe).filter_by(
            symbol=symbol
        ).distinct().all()
        timeframes = sorted([r[0] for r in rows])
        if not timeframes:
            print(f"  No candles found in DB for {symbol}.")
            return {}

    summary = {}

    for tf in timeframes:
        tf_stats = _verify_timeframe(symbol, tf, lookback_days, fix, verbose)
        summary[tf] = tf_stats

    return summary


def _verify_timeframe(
    symbol: str,
    timeframe: str,
    lookback_days: int,
    fix: bool,
    verbose: bool,
) -> dict:
    """
    Verify all candles for one (symbol, timeframe) pair.

    Steps:
      1. Determine the DB date range.
      2. Fetch all candles from Binance for that range.
      3. Cross-check every DB candle against the Binance truth.
      4. Report missing candles (Binance has, DB doesn't).
    """
    print(f"\n  ══ {symbol} / {timeframe} ══")

    # ── 1. Determine date range from DB ──────────────────────────
    db_range = db.session.query(
        db.func.min(CandleModel.open_time),
        db.func.max(CandleModel.open_time),
    ).filter_by(symbol=symbol, timeframe=timeframe).first()

    if not db_range or db_range[0] is None:
        print(f"     No candles in DB for {symbol}/{timeframe}")
        return {'db_total': 0, 'mismatched': 0, 'missing': 0, 'extra': 0, 'ok': 0}

    db_earliest: datetime = db_range[0]
    db_latest: datetime = db_range[1]

    # Clamp lookback: don't fetch more than `lookback_days` from now
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    start_dt = max(db_earliest, cutoff)

    print(f"     DB range: {db_earliest.isoformat()} → {db_latest.isoformat()}")
    print(f"     Verifying last {lookback_days}d: {start_dt.isoformat()} → {db_latest.isoformat()}")

    # ── 2. Fetch Binance truth data ──────────────────────────────
    start_ms = _datetime_to_binance_ms(start_dt)
    end_ms = _datetime_to_binance_ms(db_latest) + _get_timeframe_ms(timeframe)

    print(f"     Fetching from Binance ...", end='', flush=True)
    try:
        binance_candles = fetch_klines(symbol, timeframe, start_ms, end_ms)
    except Exception as e:
        print(f"\n     ERROR fetching from Binance: {e}")
        return {'db_total': 0, 'mismatched': 0, 'missing': 0, 'extra': 0, 'ok': 0, 'error': str(e)}

    print(f" {len(binance_candles)} candles received from Binance")

    if not binance_candles:
        print("     No Binance data returned — skipping.")
        return {'db_total': 0, 'mismatched': 0, 'missing': 0, 'extra': 0, 'ok': 0}

    # Build O(1) lookup index from Binance data
    binance_index = _build_binance_index(binance_candles)

    # ── 3. Fetch DB candles within the verified range ─────────────
    db_candles = (
        CandleModel.query
        .filter_by(symbol=symbol, timeframe=timeframe)
        .filter(CandleModel.open_time >= start_dt)
        .filter(CandleModel.open_time <= db_latest)
        .order_by(CandleModel.open_time.asc())
        .all()
    )

    print(f"     {len(db_candles)} candles in DB for this range")

    # ── 4. Build set of DB open_times for gap detection ──────────
    db_times: set[datetime] = {c.open_time for c in db_candles}

    # ── 5. Cross-check every DB candle ───────────────────────────
    mismatched: list[dict] = []   # DB value != Binance value
    repaired: list[dict] = []     # Successfully fixed

    for db_c in db_candles:
        truth = binance_index.get(db_c.open_time)
        if truth is None:
            continue  # Not in the Binance range — likely outside verified window

        diffs = []

        if not _float_close(db_c.open, float(truth['open'])):
            diffs.append(('open', db_c.open, float(truth['open'])))
        if not _float_close(db_c.high, float(truth['high'])):
            diffs.append(('high', db_c.high, float(truth['high'])))
        if not _float_close(db_c.low, float(truth['low'])):
            diffs.append(('low', db_c.low, float(truth['low'])))
        if not _float_close(db_c.close, float(truth['close'])):
            diffs.append(('close', db_c.close, float(truth['close'])))
        if not _float_close(db_c.volume, float(truth['volume'])):
            diffs.append(('volume', db_c.volume, float(truth['volume'])))

        if diffs:
            entry = {
                'open_time': db_c.open_time,
                'db': {f: getattr(db_c, f) for f, _, _ in diffs},
                'binance': {f: v for f, _, v in diffs},
                'diffs': diffs,
            }
            mismatched.append(entry)

            if verbose:
                ts = db_c.open_time.isoformat()
                for field, db_val, bn_val in diffs:
                    print(f"       ❌ {ts}  {field}: DB={db_val}  Binance={bn_val}")

            if fix:
                db_c.open = float(truth['open'])
                db_c.high = float(truth['high'])
                db_c.low = float(truth['low'])
                db_c.close = float(truth['close'])
                db_c.volume = float(truth['volume'])
                repaired.append(entry)

    # ── 6. Detect missing candles (Binance has, DB doesn't) ─────
    missing: list[datetime] = []
    for bn_c in binance_candles:
        bn_time = bn_c['open_time']
        if isinstance(bn_time, int):
            bn_time = _binance_to_datetime(bn_time)
        if bn_time < start_dt:
            continue
        if bn_time not in db_times:
            missing.append(bn_time)

    # ── 7. Detect extra candles (DB has, Binance doesn't) ────────
    extra: list[datetime] = []
    binance_times: set[datetime] = set()
    for bn_c in binance_candles:
        bn_time = bn_c['open_time']
        if isinstance(bn_time, int):
            bn_time = _binance_to_datetime(bn_time)
        binance_times.add(bn_time)

    for db_c in db_candles:
        if db_c.open_time >= start_dt and db_c.open_time not in binance_times:
            extra.append(db_c.open_time)

    # ── 8. Commit repairs ────────────────────────────────────────
    if repaired:
        db.session.commit()
        print(f"     🔧 Repaired {len(repaired)} corrupted candles")

    # ── 9. Print summary ─────────────────────────────────────────
    ok = len(db_candles) - len(mismatched) - len(extra)
    stats = {
        'db_total': len(db_candles),
        'binance_total': len(binance_candles),
        'mismatched': len(mismatched),
        'repaired': len(repaired),
        'missing': len(missing),
        'extra': len(extra),
        'ok': ok,
    }

    print(f"     ──────────────────────────────────────────")
    print(f"     DB candles checked : {stats['db_total']:>6d}")
    print(f"     Binance candles    : {stats['binance_total']:>6d}")
    print(f"     ✅ OK              : {stats['ok']:>6d}")
    print(f"     ❌ Mismatched       : {stats['mismatched']:>6d}" +
          (f" ({stats['repaired']} repaired)" if stats['repaired'] else ""))
    print(f"     📭 Missing (gap)   : {stats['missing']:>6d}")
    print(f"     👻 Extra (stale)   : {stats['extra']:>6d}")

    if missing and len(missing) <= 20:
        for mt in missing[:20]:
            print(f"         - {mt.isoformat()}")
    elif missing:
        print(f"         (showing first 20 of {len(missing)})")
        for mt in missing[:20]:
            print(f"         - {mt.isoformat()}")

    if extra and len(extra) <= 20:
        for et in extra[:20]:
            print(f"         - {et.isoformat()}")
    elif extra:
        print(f"         (showing first 20 of {len(extra)})")
        for et in extra[:20]:
            print(f"         - {et.isoformat()}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Cross-check local candle data against Binance API"
    )
    parser.add_argument(
        '--symbol', type=str, default=None,
        help='Trading pair to verify (default: all symbols in DB)'
    )
    parser.add_argument(
        '--timeframe', type=str, default=None,
        help='Timeframe to verify (default: all timeframes in DB)'
    )
    parser.add_argument(
        '--days', type=int, default=30,
        help='How many days of recent data to verify (default: 30)'
    )
    parser.add_argument(
        '--fix', action='store_true',
        help='Repair corrupted OHLCV values with Binance truth data'
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Print every mismatched candle'
    )
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        # Resolve symbols to verify
        if args.symbol:
            symbols = [args.symbol.upper()]
        else:
            rows = db.session.query(CandleModel.symbol).distinct().all()
            symbols = sorted([r[0] for r in rows])

        if not symbols:
            print("No candle data found in the database.")
            return

        # Resolve timeframes
        if args.timeframe:
            timeframes = [args.timeframe]
        else:
            timeframes = None  # verify_all will auto-detect

        print("=" * 65)
        print("  CANDLE DATA INTEGRITY VERIFIER")
        print(f"  Symbols   : {', '.join(symbols)}")
        if timeframes:
            print(f"  Timeframes: {', '.join(timeframes)}")
        else:
            print(f"  Timeframes: all (auto-detected per symbol)")
        print(f"  Lookback  : {args.days} days")
        print(f"  Fix mode  : {'ON' if args.fix else 'OFF'}")
        print("=" * 65)

        # ── Run verification ─────────────────────────────────────
        grand_total = {
            'db_total': 0,
            'mismatched': 0,
            'repaired': 0,
            'missing': 0,
            'extra': 0,
            'ok': 0,
        }

        for symbol in symbols:
            print(f"\n── {symbol} ──")
            summary = verify_symbol(
                symbol=symbol,
                timeframes=timeframes,
                lookback_days=args.days,
                fix=args.fix,
                verbose=args.verbose,
            )
            for tf, stats in summary.items():
                for k in grand_total:
                    grand_total[k] += stats.get(k, 0)

        # ── Grand total ──────────────────────────────────────────
        print("\n" + "=" * 65)
        print("  GRAND TOTAL")
        print(f"  Total DB candles checked : {grand_total['db_total']:>6d}")
        print(f"  ✅ OK                    : {grand_total['ok']:>6d}")
        print(f"  ❌ Mismatched (corrupted): {grand_total['mismatched']:>6d}" +
              (f" ({grand_total['repaired']} repaired)" if grand_total['repaired'] else ""))
        print(f"  📭 Missing (gaps)        : {grand_total['missing']:>6d}")
        print(f"  👻 Extra (stale)         : {grand_total['extra']:>6d}")
        print("=" * 65)

        if grand_total['mismatched'] > 0 and not args.fix:
            print("\n  Hint: Run with --fix to repair corrupted candles.")
        if grand_total['missing'] > 0:
            print("  Hint: Missing candles may indicate historical data gaps.")
            print("        Run a backfill to fill them in.")


if __name__ == '__main__':
    main()
