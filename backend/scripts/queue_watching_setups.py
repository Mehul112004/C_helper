import sys
import os
import time

# Ensure the 'backend' directory is in the python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.models.db import db, WatchingSetup
from app.core.base_strategy import SetupSignal
from app.core.strategy_runner import StrategyRunner
from app.core.strategy_loader import registry
from app.core.llm_queue import llm_queue
from app.core.data_utils import get_finalized_candles

def process_watching_setups():
    app = create_app()
    with app.app_context():
        llm_queue.set_app(app)
        llm_queue.start()

        setups = WatchingSetup.query.filter_by(status='WATCHING').all()
        print(f"Found {len(setups)} setups in WATCHING state.\n")

        enqueued_count = 0

        for setup in setups:
            print(f"Queueing: {setup.id} ({setup.symbol} {setup.timeframe} {setup.strategy_name})")

            strategy = registry.get_by_name(setup.strategy_name)
            if not strategy:
                print(f"  -> ⚠ Strategy '{setup.strategy_name}' not found in registry. Skipping.")
                continue

            if setup.timeframe not in strategy.timeframes:
                print(f"  -> ⚠ Timeframe {setup.timeframe} not supported by {setup.strategy_name}. Skipping.")
                continue

            # Reconstruct SetupSignal
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

            # Build pre_processed_df using the strategy's pipeline
            try:
                lookback = strategy.get_required_lookback()
                df = get_finalized_candles(setup.symbol, setup.timeframe, limit=lookback)

                if len(df) < strategy.get_min_candles():
                    print(f"  -> ⚠ Not enough candles ({len(df)}). Skipping.")
                    continue

                df = strategy.pre_process(df, symbol=setup.symbol, timeframe=setup.timeframe)
                df = strategy.generate_signals(df)
            except Exception as e:
                print(f"  -> ⚠ Failed to build pre_processed_df: {e}")
                continue

            # Enqueue for LLM evaluation
            llm_queue.enqueue_signal(
                watching_setup_id=setup.id,
                signal=signal,
                pre_processed_df=df,
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
