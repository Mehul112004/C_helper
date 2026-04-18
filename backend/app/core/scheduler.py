"""
Background Refresh Scheduler
Uses APScheduler to periodically recalculate S/R zones.
- Full 4h refresh: every 4h candle close (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
- Full 1D refresh: daily at 00:02 UTC (only once per day)
- Minor update: every 1h candle close

All jobs filter to active sessions only (FIX-SCH-1), use staggered minute
offsets to avoid concurrent DB commits (FIX-SCH-5), and include
coalesce + max_instances guards (FIX-SCH-10).
"""

import atexit
from apscheduler.schedulers.background import BackgroundScheduler
from app.core.sr_engine import SREngine
from app.core.indicators import IndicatorService
from app.core.config import SUPPORTED_SYMBOLS


# Timeframes for each job type
FULL_REFRESH_4H_TIMEFRAMES = ['4h']
FULL_REFRESH_1D_TIMEFRAMES = ['1D']
MINOR_UPDATE_TIMEFRAMES = ['1h', '15m']

scheduler = BackgroundScheduler(daemon=True)


def _get_active_symbols(scanner):
    """Return symbols with active sessions, or empty list if none."""
    try:
        active_sessions = scanner.get_active_sessions()
        return list({s['symbol'] for s in active_sessions})
    except Exception:
        return []


def full_zone_refresh_4h(app, scanner):
    """
    Runs every 4 hours (aligned to 4h candle closes).
    For each active symbol × [4h]: full detection → merge → score → persist.
    Invalidates indicator cache for affected symbol/timeframe pairs.
    """
    with app.app_context():
        active_symbols = _get_active_symbols(scanner)
        if not active_symbols:
            print("[Scheduler] No active sessions — skipping 4h full refresh.")
            return
        print(f"[Scheduler] Starting 4h S/R zone refresh for {active_symbols}...")
        for symbol in active_symbols:
            for timeframe in FULL_REFRESH_4H_TIMEFRAMES:
                try:
                    SREngine.full_refresh(symbol, timeframe)
                    IndicatorService.invalidate_cache(symbol, timeframe)
                except Exception as e:
                    print(f"[Scheduler] Error refreshing {symbol}/{timeframe}: {e}")
        print("[Scheduler] 4h full zone refresh complete.")


def full_zone_refresh_1d(app, scanner):
    """
    Runs once per day at 00:02 UTC (after daily candle close).
    For each active symbol × [1D]: full detection → merge → score → persist.
    """
    with app.app_context():
        active_symbols = _get_active_symbols(scanner)
        if not active_symbols:
            print("[Scheduler] No active sessions — skipping 1D full refresh.")
            return
        print(f"[Scheduler] Starting 1D S/R zone refresh for {active_symbols}...")
        for symbol in active_symbols:
            for timeframe in FULL_REFRESH_1D_TIMEFRAMES:
                try:
                    SREngine.full_refresh(symbol, timeframe)
                    IndicatorService.invalidate_cache(symbol, timeframe)
                except Exception as e:
                    print(f"[Scheduler] Error refreshing {symbol}/{timeframe}: {e}")
        print("[Scheduler] 1D full zone refresh complete.")


def minor_zone_update(app, scanner):
    """
    Runs every 1 hour at :03.
    For each active symbol × [1h, 15m]: swing point detection on latest window.
    Adds new swing points to DB without full recalculation.
    """
    with app.app_context():
        active_symbols = _get_active_symbols(scanner)
        if not active_symbols:
            print("[Scheduler] No active sessions — skipping minor update.")
            return
        print(f"[Scheduler] Starting minor S/R zone update for {active_symbols}...")
        for symbol in active_symbols:
            for timeframe in MINOR_UPDATE_TIMEFRAMES:
                try:
                    SREngine.minor_update(symbol, timeframe)
                except Exception as e:
                    print(f"[Scheduler] Error updating {symbol}/{timeframe}: {e}")
        print("[Scheduler] Minor zone update complete.")


def startup_full_refresh(app, scanner):
    """
    One-shot refresh fired on application boot (FIX-SCH-7).
    Ensures zones are fresh even if the server restarted mid-cycle.
    """
    with app.app_context():
        active_symbols = _get_active_symbols(scanner)
        if not active_symbols:
            # On cold start there may be no active sessions yet — refresh all supported symbols
            active_symbols = SUPPORTED_SYMBOLS
        print(f"[Scheduler] Startup full refresh for {active_symbols}...")
        for symbol in active_symbols:
            for timeframe in FULL_REFRESH_4H_TIMEFRAMES + FULL_REFRESH_1D_TIMEFRAMES:
                try:
                    SREngine.full_refresh(symbol, timeframe)
                    IndicatorService.invalidate_cache(symbol, timeframe)
                except Exception as e:
                    print(f"[Scheduler] Startup refresh error {symbol}/{timeframe}: {e}")
        print("[Scheduler] Startup full refresh complete.")


def init_scheduler(app, scanner):
    """
    Initialize and start the background scheduler within the Flask app context.
    Jobs are scheduled to run 1 minute after candle close times to ensure
    the closing candle has been stored in the database.

    Args:
        app: Flask application instance
        scanner: LiveScanner instance (for active session filtering)
    """
    # --- Cold-start: immediate one-shot refresh (FIX-SCH-7) ---
    scheduler.add_job(
        func=startup_full_refresh,
        args=[app, scanner],
        trigger='date',  # fire once immediately
        id='startup_full_refresh',
        replace_existing=True,
    )

    # --- 4h zones: every 4h at :01 (FIX-SCH-2/5) ---
    scheduler.add_job(
        func=full_zone_refresh_4h,
        args=[app, scanner],
        trigger='cron',
        hour='0,4,8,12,16,20',
        minute=1,
        id='full_zone_refresh_4h',
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=120,
    )

    # --- 1D zones: only at daily close 00:02 UTC (FIX-SCH-2/5) ---
    scheduler.add_job(
        func=full_zone_refresh_1d,
        args=[app, scanner],
        trigger='cron',
        hour=0,
        minute=2,
        id='full_zone_refresh_1d',
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=180,
    )

    # --- Minor update (1h/15m): every hour at :03 (FIX-SCH-2/5) ---
    scheduler.add_job(
        func=minor_zone_update,
        args=[app, scanner],
        trigger='cron',
        minute=3,
        id='minor_zone_update',
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    scheduler.start()
    print("[Scheduler] Background scheduler started.")
    print("[Scheduler] 4h full refresh: every 4h at :01 UTC")
    print("[Scheduler] 1D full refresh: daily at 00:02 UTC")
    print("[Scheduler] Minor zone update: every 1h at :03 UTC")

    # Ensure scheduler shuts down cleanly when the app exits
    atexit.register(lambda: scheduler.shutdown(wait=False))
