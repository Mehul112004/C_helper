import os
import sys
import json
import subprocess
from datetime import datetime, timedelta

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
    app = create_app()
    with app.app_context():
        commit_id = get_git_commit_id()
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(days=120)
        
        symbols = ["BTCUSDT", "ETHUSDT"]
        timeframes = BacktestEngine.VALID_TIMEFRAMES
        
        print("Loading built-in strategies...")
        registry.load_builtin_strategies()
        registry.sync_with_db()
        enabled_strategies = registry.get_enabled()
        
        results = {
            "last_git_commit_id": commit_id,
            "date": end_dt.strftime("%Y-%m-%d"),
            "runs": []
        }
        
        for symbol in symbols:
            for tf in timeframes:
                print(f"\n--- Processing {symbol} on {tf} ---")
                try:
                    sync_data_for_timeframe(symbol, tf, start_dt, end_dt)
                except Exception as e:
                    print(f"Failed to sync data for {symbol} {tf}: {e}")
                    continue
                
                for strat in enabled_strategies:
                    if tf in strat.timeframes:
                        print(f"Running backtest for {strat.name}...")
                        try:
                            # The BacktestEngine runs strategy bar-by-bar
                            res = BacktestEngine.run(
                                symbol=symbol,
                                timeframe=tf,
                                start_date=start_dt,
                                end_date=end_dt,
                                strategies=[strat],
                                strategy_names=[strat.name],
                                initial_capital=10000.0,
                                risk_pct=0.01
                            )
                            
                            results["runs"].append({
                                "symbol": symbol,
                                "timeframe": tf,
                                "strategy_name": strat.name,
                                "run_id": res.get("run_id"),
                                "status": res.get("status"),
                                "metrics": res.get("metrics"),
                                "trades": res.get("trades", []),
                                "equity_curve": res.get("equity_curve", [])
                            })
                            
                            print(f"  -> Status: {res.get('status')}. Trades: {res.get('trade_count')}")
                        except Exception as e:
                            print(f"  -> Error running backtest: {e}")
                            
        # Save to file
        date_str = results["date"]                      # e.g. "2026-04-21"
        date_compact = date_str.replace("-", "")        # e.g. "20260421" (folder name)
        project_root = os.path.dirname(backend_dir)
        backtests_dir = os.path.join(project_root, "backtests", date_compact)
        os.makedirs(backtests_dir, exist_ok=True)
        
        # Determine the correct version number
        version = 1
        while True:
            filepath = os.path.join(backtests_dir, f"{date_str}_backtests_v{version}.json")
            if not os.path.exists(filepath):
                break
            version += 1
            
        with open(filepath, "w") as f:
            json.dump(results, f, indent=2, default=str)
            
        # Also save a brief version without trades and equity_curve
        brief_results = {
            "last_git_commit_id": results["last_git_commit_id"],
            "date": results["date"],
            "runs": [
                {k: v for k, v in run.items() if k not in ("trades", "equity_curve")}
                for run in results["runs"]
            ]
        }
        brief_filepath = os.path.join(backtests_dir, f"{date_str}_backtests_v{version}_brief.json")
        with open(brief_filepath, "w") as f:
            json.dump(brief_results, f, indent=2, default=str)
            
        print(f"\nAll backtests complete. Results saved to:")
        print(f"  Full:  {filepath}")
        print(f"  Brief: {brief_filepath}")

if __name__ == "__main__":
    run_backtests()
