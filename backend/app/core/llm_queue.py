import threading
import queue
import time
import logging
from typing import Dict, Any, Tuple
import uuid

from app.core.base_strategy import SetupSignal, Candle, Indicators
from app.core.llm_client import LLMClient
from app.core.telegram_queue import telegram_queue
from app.core.outcome_tracker import outcome_tracker
from app.core.sse import sse_manager

logger = logging.getLogger(__name__)

# Queue payload type: 
# (watching_setup_id, SetupSignal, candles_list, indicators_obj, sr_zones_list, htf_candles)
QueuePayload = Tuple[str, SetupSignal, list[Candle], Indicators, list[dict], list[Candle]]

class LLMQueueManager:
    """
    Background worker that processes SetupSignals through the LLM.
    Prevents the live scanner (which runs on Binance WS events) from blocking.
    """
    def __init__(self):
        self._q = queue.Queue()
        self._worker_thread = None
        self._stop_event = threading.Event()
        self._app = None
        
    def set_app(self, app):
        """Pass the Flask application context."""
        self._app = app
        
    def start(self):
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(target=self._run_worker, daemon=True, name="LLMWorker")
            self._worker_thread.start()
            logger.info("LLM background worker started.")

    def stop(self):
        self._stop_event.set()
        if self._worker_thread:
            # We put a dummy item to break the blocking get() if empty
            self._q.put(None)
            self._worker_thread.join(timeout=2)
            logger.info("LLM background worker stopped.")

    def enqueue_signal(self, watching_setup_id: str, signal: SetupSignal, candles: list[Candle], indicators: Indicators, sr_zones: list[dict], htf_candles: list[Candle] = None):
        """Place a candidate signal in the queue to be evaluated."""
        self._q.put((watching_setup_id, signal, candles, indicators, sr_zones, htf_candles))
        logger.info(f"Enqueued signal for {signal.symbol} / {signal.strategy_name}. Queue size: {self._q.qsize()}")

    def _run_worker(self):
        MAX_RETRIES = 3
        RETRY_DELAYS = [15, 30, 60]  # Increasing backoff

        while not self._stop_event.is_set():
            try:
                # Block for up to 1 second
                item = self._q.get(timeout=1)
                if item is None:
                    continue  # Stop signal injected

                # Items can be 6-tuple or 7-tuple (with retry count)
                if len(item) == 6:
                    watching_setup_id, signal, candles, indicators, sr_zones, htf_candles = item
                    retry_count = 0
                else:
                    watching_setup_id, signal, candles, indicators, sr_zones, htf_candles, retry_count = item

                # Check LM Studio connectivity
                if not LLMClient.ping_status():
                    logger.warning("LM Studio is unreachable. Backing off 30s and requeuing.")
                    time.sleep(30)
                    self._q.put((watching_setup_id, signal, candles, indicators, sr_zones, htf_candles, retry_count))
                    continue
                
                logger.info(f"Processing LLM evaluation for {signal.symbol} - {signal.strategy_name} "
                            f"(attempt {retry_count + 1}/{MAX_RETRIES + 1})")
                verdict_data, prompt, raw_response = LLMClient.evaluate_signal(signal, candles, indicators, sr_zones, htf_candles)
                
                # Log every interaction
                self._log_prompt(watching_setup_id, signal, verdict_data, prompt, raw_response)
                
                if verdict_data:
                    logger.info(f"[LLMQueue] Verdict={verdict_data.verdict} confidence={verdict_data.confidence_score}/10 "
                                f"for {signal.symbol}/{signal.strategy_name}")
                    self._handle_verdict(watching_setup_id, signal, verdict_data)
                else:
                    if retry_count < MAX_RETRIES:
                        delay = RETRY_DELAYS[min(retry_count, len(RETRY_DELAYS) - 1)]
                        logger.warning(f"LLM returned no valid verdict. Retry {retry_count + 1}/{MAX_RETRIES} "
                                       f"after {delay}s delay.")
                        time.sleep(delay)
                        self._q.put((watching_setup_id, signal, candles, indicators, sr_zones, htf_candles, retry_count + 1))
                    else:
                        logger.error(f"LLM failed after {MAX_RETRIES + 1} attempts for "
                                     f"{signal.symbol}/{signal.strategy_name}. Dropping signal.")
                    
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in LLM queue worker: {e}")
                time.sleep(5)

    def _log_prompt(self, watching_setup_id: str, signal: SetupSignal, verdict_data, prompt: str, raw_response: str):
        if not self._app:
            return
        with self._app.app_context():
            from app.models.db import db, LLMPromptLog
            from app.core.llm_client import LM_STUDIO_MODEL
            
            parsed_verdict = verdict_data.verdict if verdict_data else 'ERROR'
            
            try:
                new_log = LLMPromptLog(
                    watching_setup_id=watching_setup_id,
                    symbol=signal.symbol,
                    strategy_name=signal.strategy_name,
                    model_name=LM_STUDIO_MODEL,
                    prompt_text=prompt,
                    response_text=raw_response,
                    parsed_verdict=parsed_verdict
                )
                db.session.add(new_log)
                db.session.commit()
                
                # Cleanup: keep only last 1000
                count = db.session.query(LLMPromptLog).count()
                if count > 1000:
                    subq = db.session.query(LLMPromptLog.id).order_by(LLMPromptLog.id.desc()).offset(1000).subquery()
                    db.session.query(LLMPromptLog).filter(LLMPromptLog.id.in_(subq)).delete(synchronize_session=False)
                    db.session.commit()
            except Exception as e:
                logger.error(f"Failed to log LLM prompt: {e}")

    def _handle_verdict(self, watching_setup_id: str, signal: SetupSignal, verdict_data):
        if not self._app:
            logger.error("Flask app context not set in LLMQueueManager")
            return
            
        with self._app.app_context():
            from app.models.db import db, ConfirmedSignal, WatchingSetup, RejectedSignal
            
            w_setup = WatchingSetup.query.get(watching_setup_id)
            if not w_setup:
                return

            v_str = verdict_data.verdict
            
            # Map LLM verdict string to formal database schema state
            if v_str in ('CONFIRM', 'MODIFY'):
                w_setup.status = 'CONFIRMED'
            else:
                w_setup.status = 'REJECTED'
            
            # Broadcast state change to clients (which natively clears it out of the watching UI)
            sse_manager.publish('setup_updated', w_setup.to_dict())
            
            if v_str in ('CONFIRM', 'MODIFY'):
                # Handle modifying the levels
                db_entry = signal.entry if signal.entry else getattr(w_setup, 'entry', 0.0)
                db_sl = verdict_data.modified_sl if v_str == 'MODIFY' and verdict_data.modified_sl else getattr(w_setup, 'sl', 0.0)
                db_tp1 = verdict_data.modified_tp1 if v_str == 'MODIFY' and verdict_data.modified_tp1 else getattr(w_setup, 'tp1', 0.0)
                db_tp2 = verdict_data.modified_tp2 if v_str == 'MODIFY' and verdict_data.modified_tp2 else getattr(w_setup, 'tp2', 0.0)
                
                new_sig = ConfirmedSignal(
                    id=str(uuid.uuid4()),
                    watching_setup_id=watching_setup_id,
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    direction=signal.direction,
                    strategy_name=signal.strategy_name,
                    confidence=signal.confidence,
                    entry=db_entry,
                    sl=db_sl,
                    tp1=db_tp1,
                    tp2=db_tp2,
                    verdict_status=v_str,
                    reasoning_text=verdict_data.reasoning,
                    trade_outcome='ACTIVE'
                )
                db.session.add(new_sig)
                db.session.commit()
                
                # Emit SSE for Confirmed feed
                payload = new_sig.to_dict()
                payload['session_id'] = w_setup.session_id
                sse_manager.publish('signal_confirmed', payload)
                logger.info(f"Signal for {signal.symbol} confirmed by LLM ('{v_str}') and saved to DB.")
                
                # Trigger Telegram Notification
                telegram_queue.enqueue_confirm_alert(new_sig.id)
                
                # Add to OutcomeTracker for live price checking
                outcome_tracker.add_to_cache(new_sig)
            
            else: # REJECT
                db_entry = signal.entry if signal.entry else getattr(w_setup, 'entry', 0.0)
                db_sl = getattr(w_setup, 'sl', 0.0)
                db_tp1 = getattr(w_setup, 'tp1', 0.0)
                db_tp2 = getattr(w_setup, 'tp2', 0.0)

                new_rejected = RejectedSignal(
                    id=str(uuid.uuid4()),
                    watching_setup_id=watching_setup_id,
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    direction=signal.direction,
                    strategy_name=signal.strategy_name,
                    confidence=signal.confidence,
                    entry=db_entry,
                    sl=db_sl,
                    tp1=db_tp1,
                    tp2=db_tp2,
                    reasoning_text=verdict_data.reasoning
                )
                db.session.add(new_rejected)
                db.session.commit()
                sse_manager.publish('setup_rejected', w_setup.to_dict())
                logger.info(f"Signal for {signal.symbol} REJECTED by LLM. {verdict_data.reasoning}")
                
                # Trigger Telegram Notification for REJECT
                telegram_queue.enqueue_reject_alert(watching_setup_id, verdict_data.reasoning)

llm_queue = LLMQueueManager()
