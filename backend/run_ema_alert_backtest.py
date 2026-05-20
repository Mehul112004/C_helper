"""
Backtest runner for EMA Cross Alert strategy.
Runs the strategy across 45 days of historical data for 30m/1h timeframes,
captures all alert events, and exports them to a JSON file.

Usage: python3 run_ema_alert_backtest.py
Output: ema_alert_backtest_results.json
"""

import sys
sys.path.insert(0, '.')

import json
import logging
from datetime import datetime, timezone, timedelta

import pandas as pd

from app import create_app
from app.core.data_utils import get_finalized_candles
from app.strategies.ema_cross_alert import EMACrossAlert, _escape_md
from app.core.indicators import compute_ema, compute_rsi, compute_atr

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAMES = ["30m", "1h"]
DAYS_BACK = 45


def run_backtest():
    app = create_app()
    results = {
        "strategy": "EMA Cross Alert",
        "description": "EMA 9/20 imminent crossover alerts",
        "period_days": DAYS_BACK,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "near_threshold_multiplier": 0.08,
            "min_near_pct": 0.0003,
            "cool down_hours": 4,
        },
        "alerts": [],
        "summary": {},
    }

    with app.app_context():
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                print(f"\n{'='*60}")
                print(f"Running {symbol} {tf}...")
                print(f"{'='*60}")

                end_date = datetime.now(timezone.utc)
                start_date = end_date - timedelta(days=DAYS_BACK)

                try:
                    df = get_finalized_candles(
                        symbol=symbol,
                        timeframe=tf,
                        start_date=start_date,
                        end_date=end_date,
                    )
                except Exception as e:
                    print(f"  Skipping {symbol}/{tf}: {e}")
                    continue

                if len(df) < 100:
                    print(f"  Skipping {symbol}/{tf}: only {len(df)} candles")
                    continue

                print(f"  Loaded {len(df)} candles")
                print(f"  Range: {df['open_time'].iloc[0]} → {df['open_time'].iloc[-1]}")

                strategy = EMACrossAlert()
                df = strategy.pre_process(df, symbol=symbol, timeframe=tf)
                alerts = simulate_alerts(strategy, df, symbol, tf)

                print(f"  Alerts generated: {len(alerts)}")
                for a in alerts:
                    print(f"    {a['timestamp'][:19]}  {a['direction']:7s}  "
                          f"price={a['price']:,.4f}  div={a['rsi_divergence']}")

                results["alerts"].extend(alerts)

    # Build summary
    results["alerts"].sort(key=lambda a: a["timestamp"])
    results["summary"] = {
        "total_alerts": len(results["alerts"]),
        "by_timeframe": {},
        "by_symbol": {},
        "by_direction": {"bullish": 0, "bearish": 0},
    }
    for a in results["alerts"]:
        tf = a["timeframe"]
        sym = a["symbol"]
        d = a["direction"]
        results["summary"]["by_timeframe"][tf] = results["summary"]["by_timeframe"].get(tf, 0) + 1
        results["summary"]["by_symbol"][sym] = results["summary"]["by_symbol"].get(sym, 0) + 1
        results["summary"]["by_direction"][d] = results["summary"]["by_direction"].get(d, 0) + 1

    output_path = "ema_alert_backtest_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"BACKTEST COMPLETE")
    print(f"  Total alerts: {results['summary']['total_alerts']}")
    print(f"  By timeframe: {results['summary']['by_timeframe']}")
    print(f"  By symbol:    {results['summary']['by_symbol']}")
    print(f"  By direction: {results['summary']['by_direction']}")
    print(f"  Output: {output_path}")


def simulate_alerts(strategy, df, symbol, timeframe):
    """
    Walk the pre-processed DataFrame candle-by-candle and simulate
    what generate_signals would do on the most recent bar at that time.
    Captures alert metadata when conditions are met.
    """
    alerts = []
    last_alert = {}
    cooldown_hours = strategy._alert_cooldown_hours

    n = len(df)
    for idx in range(100, n):
        window = df.iloc[: idx + 1].copy()

        # Compute EMAs on this window (mimics generate_signals)
        if 'ema_9' not in window.columns:
            window['ema_9'] = compute_ema(window['close'], 9)
        if 'ema_20' not in window.columns:
            window['ema_20'] = compute_ema(window['close'], 20)

        close = window['close']
        if 'atr' in window.columns:
            atr = window['atr'].fillna(close * 0.005)
        else:
            atr = pd.Series(close * 0.005, index=window.index)

        ema9_last = window['ema_9'].iloc[-1]
        ema20_last = window['ema_20'].iloc[-1]
        ema9_prev = window['ema_9'].iloc[-2]
        ema20_prev = window['ema_20'].iloc[-2]

        if pd.isna(ema9_last) or pd.isna(ema20_last):
            continue
        if pd.isna(ema9_prev) or pd.isna(ema20_prev):
            continue

        last_close = close.iloc[-1]
        last_atr = atr.iloc[-1]
        if pd.isna(last_atr) or last_atr <= 0:
            last_atr = last_close * 0.005

        dist = abs(ema9_last - ema20_last)
        dist_prev = abs(ema9_prev - ema20_prev)
        converging = dist < dist_prev
        near_threshold = max(0.08 * last_atr, last_close * 0.0003)
        near = dist < near_threshold

        if not (near and converging):
            continue

        direction = 'bullish' if ema9_last < ema20_last else 'bearish'

        candle_time = window['open_time'].iloc[-1]
        if hasattr(candle_time, 'to_pydatetime'):
            candle_time = candle_time.to_pydatetime()

        alert_key = (symbol, timeframe, direction)
        last_time = last_alert.get(alert_key)
        if last_time and (candle_time - last_time).total_seconds() < cooldown_hours * 3600:
            continue

        # Build context
        rsi_div = strategy._check_rsi_divergence(window, timeframe, direction)
        fvg_ob = strategy._check_fvg_ob_near(window, last_close, last_atr)
        sr_info = strategy._check_sr_near(window, last_close, last_atr)

        alerts.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": candle_time.isoformat(),
            "direction": direction,
            "direction_label": "Bullish" if direction == 'bullish' else "Bearish",
            "price": round(float(last_close), 4),
            "ema_9": round(float(ema9_last), 4),
            "ema_20": round(float(ema20_last), 4),
            "ema_distance": round(float(dist), 6),
            "atr": round(float(last_atr), 4),
            "rsi_divergence": rsi_div,
            "fvg_ob_near": fvg_ob,
            "sr_near": sr_info,
            "message": strategy._build_message(window, symbol, timeframe, direction, last_close, last_atr),
        })

        last_alert[alert_key] = candle_time

    return alerts


if __name__ == "__main__":
    run_backtest()
