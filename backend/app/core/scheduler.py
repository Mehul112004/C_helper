"""
Background Refresh Scheduler
Uses APScheduler to periodically recalculate S/R zones.
- Full refresh: every 4h candle close (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
- Minor update: every 1h candle close
"""

import atexit
from apscheduler.schedulers.background import BackgroundScheduler
from app.core.sr_engine import SREngine, SUPPORTED_SYMBOLS
from app.core.indicators import IndicatorService


# Timeframes for full refresh (4h candle close)
FULL_REFRESH_TIMEFRAMES = ['4h', '1D']

# Timeframes for minor update (1h candle close)
MINOR_UPDATE_TIMEFRAMES = ['1h', '15m']

scheduler = BackgroundScheduler(daemon=True)


def full_zone_refresh(app):
    """
    Runs every 4 hours (aligned to 4h candle closes).
    For each symbol × [4h, 1D]: run all detection methods, merge, score, persist to DB.
    Invalidates indicator cache for affected symbol/timeframe pairs.
    """
    with app.app_context():
        print("[Scheduler] Starting full S/R zone refresh...")
        for symbol in SUPPORTED_SYMBOLS:
            for timeframe in FULL_REFRESH_TIMEFRAMES:
                try:
                    SREngine.full_refresh(symbol, timeframe)
                    IndicatorService.invalidate_cache(symbol, timeframe)
                except Exception as e:
                    print(f"[Scheduler] Error refreshing {symbol}/{timeframe}: {e}")
        print("[Scheduler] Full zone refresh complete.")


def minor_zone_update(app):
    """
    Runs every 1 hour.
    For each symbol × [1h, 15m]: run swing point detection only on latest window.
    Adds new swing points to DB without full recalculation.
    """
    with app.app_context():
        print("[Scheduler] Starting minor S/R zone update...")
        for symbol in SUPPORTED_SYMBOLS:
            for timeframe in MINOR_UPDATE_TIMEFRAMES:
                try:
                    SREngine.minor_update(symbol, timeframe)
                except Exception as e:
                    print(f"[Scheduler] Error updating {symbol}/{timeframe}: {e}")
        print("[Scheduler] Minor zone update complete.")


def init_scheduler(app):
    """
    Initialize and start the background scheduler within the Flask app context.
    Jobs are scheduled to run 1 minute after candle close times to ensure
    the closing candle has been stored in the database.
    """
    # Full refresh: every 4h at :01 (1 minute after 4h candle close)
    scheduler.add_job(
        func=full_zone_refresh,
        args=[app],
        trigger='cron',
        hour='0,4,8,12,16,20',
        minute=1,
        id='full_zone_refresh',
        replace_existing=True,
        misfire_grace_time=300,  # 5 min grace for misfires
    )

    # Minor update: every hour at :01
    scheduler.add_job(
        func=minor_zone_update,
        args=[app],
        trigger='cron',
        minute=1,
        id='minor_zone_update',
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    print("[Scheduler] Background scheduler started.")
    print("[Scheduler] Full zone refresh: every 4h at :01 UTC")
    print("[Scheduler] Minor zone update: every 1h at :01 UTC")

    # Ensure scheduler shuts down cleanly when the app exits
    atexit.register(lambda: scheduler.shutdown(wait=False))
