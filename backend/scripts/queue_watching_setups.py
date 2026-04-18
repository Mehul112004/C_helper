import sys
import os
import time

# Ensure the 'backend' directory is in the python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.models.db import db, WatchingSetup, Candle as CandleModel, SRZone
from app.core.base_strategy import SetupSignal, Candle
from app.core.indicators import IndicatorService
from app.core.strategy_runner import StrategyRunner
from app.core.scanner import live_scanner
from app.core.llm_queue import llm_queue

def process_watching_setups():
    app = create_app()
    with app.app_context():
        # Force LLMQueue to know the app context and start the background worker
        llm_queue.set_app(app)
        llm_queue.start()

        setups = WatchingSetup.query.filter_by(status='WATCHING').all()
        print(f"Found {len(setups)} setups in WATCHING state.\n")

        enqueued_count = 0

        for setup in setups:
            print(f"Queueing: {setup.id} ({setup.symbol} {setup.timeframe} {setup.strategy_name})")

            # 1. Reconstruct SetupSignal
            signal = SetupSignal(
                symbol=setup.symbol,
                timeframe=setup.timeframe,
                direction=setup.direction,
                strategy_name=setup.strategy_name,
                confidence=setup.confidence,
                entry=setup.entry,
                sl=setup.sl,
                tp1=setup.tp1,
                tp2=setup.tp2,
                notes=setup.notes
            )

            # 2. Fetch candles (last 50 like the scanner does)
            db_candles = CandleModel.query.filter_by(
                symbol=setup.symbol, timeframe=setup.timeframe
            ).order_by(CandleModel.open_time.desc()).limit(50).all()

            if not db_candles:
                print(f"  -> ⚠ No candles found for {setup.symbol}/{setup.timeframe}. Skipping.")
                continue

            candle_objects = [Candle.from_db_row(c.to_dict()) for c in reversed(db_candles)]
            current_price = candle_objects[-1].close

            # 3. Compute indicators snapshot
            indicator_result = IndicatorService.compute_all(setup.symbol, setup.timeframe, include_series=True)
            series = indicator_result.get('series', {})
            candle_count = indicator_result.get('candle_count', 0)
            
            if candle_count > 0 and series:
                indicators = StrategyRunner.prepare_indicators_snapshot(series, candle_count - 1)
            else:
                print("  -> ⚠ Could not compute indicators. Skipping.")
                continue

            # 4. Fetch nearest Support & Resistance zones (within 3%)
            price_range = current_price * 0.03
            zones = SRZone.query.filter(
                SRZone.symbol == setup.symbol,
                SRZone.price_level >= current_price - price_range,
                SRZone.price_level <= current_price + price_range,
            ).all()
            sr_zones = [z.to_dict() for z in zones]

            # 5. Fetch Higher Timeframe Context
            htf_candles = live_scanner._fetch_htf_candles(setup.symbol, setup.timeframe)

            # 6. Put onto LLM Queue
            llm_queue.enqueue_signal(
                watching_setup_id=setup.id,
                signal=signal,
                candles=candle_objects,
                indicators=indicators,
                sr_zones=sr_zones,
                htf_candles=htf_candles
            )
            enqueued_count += 1
            print(f"  -> ✅ Enqueued.\n")

        print(f"Finished enqueueing {enqueued_count} signals.")
        if enqueued_count == 0:
            llm_queue.stop()
            return

        print("Waiting for LLM worker to process all inferences... (Do not terminate)")
        
        while not llm_queue._q.empty():
            time.sleep(2)
            print(f"   [Queue] items remaining: {llm_queue._q.qsize()}")
        
        # Buffer to allow the background thread to finish the *currently processing* item (which leaves the queue structure)
        print("Queue is empty, waiting 20s to ensure the final inference completes parsing and DB saving...")
        for i in range(20, 0, -1):
            sys.stdout.write(f"\rClosing in {i}s...  ")
            sys.stdout.flush()
            time.sleep(1)
        
        llm_queue.stop()
        print("\nAll inferences complete.")

if __name__ == '__main__':
    process_watching_setups()
