import os
import sys
import json
import argparse
import subprocess
from datetime import datetime, timedelta


# Single strategy on single pair
# python scripts/run_comprehensive_backtest.py --symbol BTCUSDT --strategy "EMA Crossover"
# → backtests/20260509/2026-05-09_backtests_BTCUSDT_ema_crossover.json

# Single strategy on all pairs
# python scripts/run_comprehensive_backtest.py --strategy "Order Block Retest"
# → backtests/20260509/2026-05-09_backtests_order_block_retest.json

# All strategies on single pair
# python scripts/run_comprehensive_backtest.py --symbol ETHUSDT
# → backtests/20260509/2026-05-09_backtests_ETHUSDT.json

# Single strategy, single timeframe, 30 days
# python scripts/run_comprehensive_backtest.py --symbol BTCUSDT --strategy "SMC Structure Shift" --timeframe 4h --days 30

# Skip data sync (assumes candles are already in DB)
# python scripts/run_comprehensive_backtest.py --symbol BTCUSDT --no-sync

# Custom capital and risk
# python scripts/run_comprehensive_backtest.py --capital 50000 --risk 0.02

# All pairs, all strategies (original behavior, versioned naming)
# python scripts/run_comprehensive_backtest.py
# → backtests/20260509/2026-05-09_backtests_v1.json

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func

from app import create_app
from app.models.db import db, Candle
from app.core.strategy_loader import registry
from app.core.backtest_engine import BacktestEngine
from app.utils.binance import fetch_klines


def get_git_commit_id():
    """Retrieve the current Git commit ID to track performance improvements over commits."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=backend_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Error getting git commit: {e}")
        return "unknown"


# All internal timeframes use lowercase '1d'; Binance API also accepts '1d'.
# Map is kept for explicit documentation and in case other intervals need remapping.
BINANCE_INTERVAL_MAP = {
    '1d': '1d',
}


def _strip_tz(dt):
    """Strip timezone info from a datetime so all comparisons are naive-UTC."""
    if dt is not None and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _safe_strategy_slug(name: str) -> str:
    """Convert a strategy name to a filesystem-safe slug."""
    return name.replace(" ", "_").replace("/", "_").lower()


def _build_output_path(args, date_str: str, project_root: str) -> tuple[str, str]:
    """
    Build output file paths with pair/strategy in the filename.
    Returns (full_path, brief_path).
    """
    date_compact = date_str.replace("-", "")
    backtests_dir = os.path.join(project_root, "backtests", date_compact)
    os.makedirs(backtests_dir, exist_ok=True)

    # Build filename suffix
    parts = []
    if args.symbol:
        parts.append(args.symbol)
    if args.strategy:
        parts.append(_safe_strategy_slug(args.strategy))

    if parts:
        base = f"{date_str}_backtests_{'_'.join(parts)}"
        full_path = os.path.join(backtests_dir, f"{base}.json")
        brief_path = os.path.join(backtests_dir, f"{base}_brief.json")
        return full_path, brief_path

    # No filters → use versioned naming (existing behaviour)
    version = 1
    while True:
        path = os.path.join(backtests_dir, f"{date_str}_backtests_v{version}.json")
        if not os.path.exists(path):
            break
        version += 1
    return path, path.replace(".json", "_brief.json")


def sync_data_for_timeframe(symbol: str, timeframe: str, start_dt: datetime, end_dt: datetime):
    """
    Check if we have contiguous data from start_dt to end_dt.
    If there's any gap (or no data), fetch the full 120 days.
    """
    result = db.session.query(
        func.min(Candle.open_time),
        func.max(Candle.open_time),
        func.count(Candle.open_time)
    ).filter(
        Candle.symbol == symbol,
        Candle.timeframe == timeframe,
        Candle.open_time >= start_dt,
        Candle.open_time <= end_dt
    ).first()

    min_time, max_time, count = result
    # Normalize to naive-UTC to avoid offset-naive vs offset-aware errors
    min_time = _strip_tz(min_time)
    max_time = _strip_tz(max_time)

    needs_fetch = False
    if not count or count == 0:
        needs_fetch = True
    else:
        # Check if min_time is after start_dt + 24 hours (some margin)
        if min_time > start_dt + timedelta(hours=24):
            needs_fetch = True
        # Check if max_time is before end_dt - 24 hours
        elif max_time < end_dt - timedelta(hours=24):
            needs_fetch = True

    # Check expected count as a safeguard against interstitial gaps
    if not needs_fetch:
        tf_mins = {'5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}
        mins = tf_mins.get(timeframe)
        if mins:
            expected_count = int((end_dt - start_dt).total_seconds() / 60 / mins)
            if count < expected_count * 0.95:  # 5% threshold for missed candles
                needs_fetch = True

    if needs_fetch:
        print(f"[{symbol} | {timeframe}] Gaps detected. Fetching full 120 days...")
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        # Map to Binance-compatible interval (e.g. '1D' -> '1d')
        binance_interval = BINANCE_INTERVAL_MAP.get(timeframe, timeframe)
        candles = fetch_klines(symbol, binance_interval, start_ms, end_ms)

        # The fetched candles have 'timeframe' set to the Binance interval;
        # normalise back to the internal representation before DB upsert.
        if binance_interval != timeframe:
            for c in candles:
                c['timeframe'] = timeframe

        if candles:
            print(f"[{symbol} | {timeframe}] Fetched {len(candles)} candles. Upserting into DB...")
            # Break into chunks to avoid too large SQL statements
            chunk_size = 5000
            for i in range(0, len(candles), chunk_size):
                chunk = candles[i:i + chunk_size]
                stmt = insert(Candle).values(chunk)
                do_upsert = stmt.on_conflict_do_update(
                    index_elements=['symbol', 'timeframe', 'open_time'],
                    set_={
                        'open': stmt.excluded.open,
                        'high': stmt.excluded.high,
                        'low': stmt.excluded.low,
                        'close': stmt.excluded.close,
                        'volume': stmt.excluded.volume
                    }
                )
                db.session.execute(do_upsert)
            db.session.commit()
            print(f"[{symbol} | {timeframe}] Upsert complete.")
        else:
            print(f"[{symbol} | {timeframe}] No candles fetched from Binance.")
    else:
        print(f"[{symbol} | {timeframe}] Data looks contiguous and complete. Skipping fetch.")


def run_backtests():
    parser = argparse.ArgumentParser(
        description="Run comprehensive backtests across pairs and strategies."
    )
    parser.add_argument(
        '--symbol', type=str, default=None,
        help='Trading pair to backtest (default: all pairs in DB)'
    )
    parser.add_argument(
        '--strategy', type=str, default=None,
        help='Strategy name to backtest (default: all enabled strategies)'
    )
    parser.add_argument(
        '--timeframe', type=str, default=None,
        help='Single timeframe to backtest (default: all valid timeframes)'
    )
    parser.add_argument(
        '--days', type=int, default=120,
        help='Lookback period in days (default: 120)'
    )
    parser.add_argument(
        '--capital', type=float, default=10000.0,
        help='Initial capital (default: 10000)'
    )
    parser.add_argument(
        '--risk', type=float, default=0.01,
        help='Risk per trade as decimal (default: 0.01 = 1%%)'
    )
    parser.add_argument(
        '--no-sync', action='store_true',
        help='Skip data sync (fetching candles from Binance)'
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        commit_id = get_git_commit_id()
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(days=args.days)

        # ── Resolve symbols ──────────────────────────────────────
        if args.symbol:
            symbols = [args.symbol.upper()]
        else:
            rows = db.session.query(Candle.symbol).distinct().all()
            symbols = sorted([r[0] for r in rows])

        if not symbols:
            print("No candle data found in DB. Run without --no-sync first.")
            return

        # ── Resolve timeframes ───────────────────────────────────
        if args.timeframe:
            timeframes = [args.timeframe]
        else:
            timeframes = BacktestEngine.VALID_TIMEFRAMES

        # ── Resolve strategies ───────────────────────────────────
        print("Loading built-in strategies...")
        registry.load_builtin_strategies()
        registry.sync_with_db()

        if args.strategy:
            strat = registry.get_by_name(args.strategy)
            if strat is None:
                print(f"Strategy '{args.strategy}' not found. Available:")
                for s in registry.get_all():
                    print(f"  - {s['name']}")
                return
            enabled_strategies = [strat]
        else:
            enabled_strategies = registry.get_enabled()

        # ── Print plan ───────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"  COMPREHENSIVE BACKTEST RUNNER")
        print(f"  Symbols   : {', '.join(symbols)}")
        print(f"  Timeframes: {', '.join(timeframes)}")
        print(f"  Strategies: {len(enabled_strategies)}")
        if args.strategy:
            print(f"    → {args.strategy}")
        else:
            for s in enabled_strategies:
                print(f"    - {s.name}")
        print(f"  Lookback  : {args.days} days")
        print(f"  Capital   : ${args.capital:,.2f}")
        print(f"  Risk/trade: {args.risk*100:.0f}%")
        print(f"  Data sync : {'SKIP' if args.no_sync else 'ON'}")
        print(f"{'='*60}\n")

        # ── Build output paths ───────────────────────────────────
        project_root = os.path.dirname(backend_dir)
        date_str = end_dt.strftime("%Y-%m-%d")
        full_path, brief_path = _build_output_path(args, date_str, project_root)

        results = {
            "last_git_commit_id": commit_id,
            "date": date_str,
            "config": {
                "symbols": symbols,
                "timeframes": timeframes,
                "lookback_days": args.days,
                "initial_capital": args.capital,
                "risk_per_trade": args.risk,
            },
            "runs": []
        }

        for symbol in symbols:
            for tf in timeframes:
                print(f"\n--- Processing {symbol} on {tf} ---")

                if not args.no_sync:
                    try:
                        sync_data_for_timeframe(symbol, tf, start_dt, end_dt)
                    except Exception as e:
                        print(f"Failed to sync data for {symbol} {tf}: {e}")
                        continue

                for strat in enabled_strategies:
                    if tf not in strat.timeframes:
                        continue

                    print(f"  Running backtest for {strat.name}...")
                    try:
                        res = BacktestEngine.run(
                            symbol=symbol,
                            timeframe=tf,
                            start_date=start_dt,
                            end_date=end_dt,
                            strategies=[strat],
                            strategy_names=[strat.name],
                            initial_capital=args.capital,
                            risk_pct=args.risk,
                        )

                        run_entry = {
                            "symbol": symbol,
                            "timeframe": tf,
                            "strategy_name": strat.name,
                            "run_id": res.get("run_id"),
                            "status": res.get("status"),
                            "metrics": res.get("metrics"),
                            "trades": res.get("trades", []),
                            "equity_curve": res.get("equity_curve", []),
                        }
                        results["runs"].append(run_entry)

                        print(f"    -> Status: {res.get('status')}. Trades: {res.get('trade_count')}")
                    except Exception as e:
                        print(f"    -> Error running backtest: {e}")

        # ── Save full results ────────────────────────────────────
        with open(full_path, "w") as f:
            json.dump(results, f, indent=2, default=str)

        # ── Save brief version (no trades / equity_curve bloat) ──
        brief_results = {
            "last_git_commit_id": results["last_git_commit_id"],
            "date": results["date"],
            "config": results["config"],
            "runs": [
                {k: v for k, v in run.items() if k not in ("trades", "equity_curve")}
                for run in results["runs"]
            ],
        }
        with open(brief_path, "w") as f:
            json.dump(brief_results, f, indent=2, default=str)

        print(f"\nAll backtests complete. Results saved to:")
        print(f"  Full:  {full_path}")
        print(f"  Brief: {brief_path}")


if __name__ == "__main__":
    run_backtests()
