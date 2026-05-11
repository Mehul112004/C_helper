"""
LLM Queue Manager v2 — Structured Context Evaluation

Background worker that evaluates SetupSignals through the LLM using
the new structured multi-dimensional payload from llm_context_builder.

Receives pre-processed DataFrames (not Candle/Indicators objects) so
the context builder can extract all 5 dimensions cleanly.
"""

import threading
import queue
import time
import logging
from typing import Dict, Any, Tuple
import uuid

from app.core.base_strategy import SetupSignal
from app.core.llm_client import LLMClient
from app.core.llm_context_builder import build_llm_context
from app.core.telegram_queue import telegram_queue
from app.core.outcome_tracker import outcome_tracker
from app.core.sse import sse_manager

logger = logging.getLogger(__name__)

# Queue payload: (watching_setup_id, signal, pre_processed_df, htf_data_dict)
QueuePayload = Tuple[str, SetupSignal, Any, Dict[str, Any]]


class LLMQueueManager:
    """Background worker for LLM signal evaluation with structured context."""

    def __init__(self):
        self._q = queue.Queue()
        self._worker_thread = None
        self._stop_event = threading.Event()
        self._app = None

    def set_app(self, app):
        self._app = app

    def start(self):
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._run_worker, daemon=True, name="LLMWorker"
            )
            self._worker_thread.start()
            logger.info("LLM background worker started (v2 structured context).")

    def stop(self):
        self._stop_event.set()
        if self._worker_thread:
            self._q.put(None)
            self._worker_thread.join(timeout=2)
            logger.info("LLM background worker stopped.")

    def enqueue_signal(
        self,
        watching_setup_id: str,
        signal: SetupSignal,
        pre_processed_df: Any = None,
        htf_data: Dict[str, Any] = None,
    ):
        """
        Enqueue a signal for LLM evaluation with pre-processed DataFrame context.

        Args:
            watching_setup_id: ID of the WatchingSetup
            signal: SetupSignal object
            pre_processed_df: Pre-processed DataFrame from strategy.pre_process() + generate_signals()
            htf_data: Optional dict of timeframe → pre-processed DataFrame
        """
        self._q.put((watching_setup_id, signal, pre_processed_df, htf_data or {}))
        logger.info(
            f"Enqueued signal for {signal.symbol} / {signal.strategy_name}. "
            f"Queue size: {self._q.qsize()}"
        )

    def _run_worker(self):
        MAX_RETRIES = 3
        RETRY_DELAYS = [15, 30, 60]
        PACING_DELAY = 20  # Rate limit pacing

        while not self._stop_event.is_set():
            try:
                item = self._q.get(timeout=1)
                if item is None:
                    continue

                watching_setup_id, signal, pre_df, htf_data = item[:4]

                # Build the structured context payload
                if pre_df is not None:
                    try:
                        context = build_llm_context(
                            df=pre_df,
                            signal=signal.to_dict() if hasattr(signal, 'to_dict') else {
                                'strategy_name': signal.strategy_name,
                                'timeframe': signal.timeframe,
                                'direction': signal.direction,
                                'entry': signal.entry,
                                'sl': signal.sl,
                                'tp1': signal.tp1,
                                'tp2': signal.tp2,
                                'confidence': signal.confidence,
                            },
                            symbol=signal.symbol,
                            htf_data=htf_data if htf_data else None,
                        )
                    except Exception as e:
                        logger.error(f"Failed to build LLM context: {e}")
                        self._log_prompt(watching_setup_id, signal, None, "",
                                         f"Context build error: {e}")
                        continue
                else:
                    context = {"error": "No pre-processed DataFrame available"}

                success = False
                for attempt in range(MAX_RETRIES + 1):
                    if self._stop_event.is_set():
                        break

                    if not LLMClient.ping_status():
                        logger.warning("LLM unreachable. Backing off 30s...")
                        for _ in range(30):
                            if self._stop_event.is_set():
                                break
                            time.sleep(1)
                        continue

                    logger.info(
                        f"LLM evaluation: {signal.symbol} {signal.strategy_name} "
                        f"(attempt {attempt + 1}/{MAX_RETRIES + 1})"
                    )

                    verdict_data, prompt, raw_response = LLMClient.evaluate_signal(context)

                    # Log the interaction
                    self._log_prompt(watching_setup_id, signal, verdict_data, prompt, raw_response)

                    if verdict_data:
                        logger.info(
                            f"[LLMQueue] Verdict={verdict_data.verdict} "
                            f"confidence={verdict_data.confidence_score}/10 "
                            f"for {signal.symbol}/{signal.strategy_name}"
                        )
                        self._handle_verdict(watching_setup_id, signal, verdict_data)
                        success = True

                        # Rate limit pacing
                        logger.info(f"Pacing {PACING_DELAY}s for rate limits...")
                        for _ in range(PACING_DELAY):
                            if self._stop_event.is_set():
                                break
                            time.sleep(1)
                        break
                    else:
                        if attempt < MAX_RETRIES:
                            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                            logger.warning(
                                f"LLM returned no verdict. Retry {attempt + 1}/{MAX_RETRIES} "
                                f"after {delay}s."
                            )
                            for _ in range(delay):
                                if self._stop_event.is_set():
                                    break
                                time.sleep(1)
                        else:
                            logger.error(
                                f"LLM failed after {MAX_RETRIES + 1} attempts for "
                                f"{signal.symbol}/{signal.strategy_name}. Dropping signal."
                            )

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in LLM queue worker: {e}")
                time.sleep(5)

    def _log_prompt(self, watching_setup_id, signal, verdict_data, prompt, raw_response):
        if not self._app:
            return
        with self._app.app_context():
            from app.models.db import db, LLMPromptLog
            from app.core.llm_providers.factory import get_llm_provider

            parsed_verdict = verdict_data.verdict if verdict_data else 'ERROR'

            try:
                provider = get_llm_provider()
                new_log = LLMPromptLog(
                    watching_setup_id=watching_setup_id,
                    symbol=signal.symbol,
                    strategy_name=signal.strategy_name,
                    model_name=provider.model,
                    prompt_text=prompt[:2000],
                    response_text=raw_response[:2000] if raw_response else "",
                    parsed_verdict=parsed_verdict,
                )
                db.session.add(new_log)
                db.session.commit()

                # Cleanup old logs
                count = db.session.query(LLMPromptLog).count()
                if count > 1000:
                    subq = (
                        db.session.query(LLMPromptLog.id)
                        .order_by(LLMPromptLog.id.desc())
                        .offset(1000)
                        .subquery()
                    )
                    db.session.query(LLMPromptLog).filter(
                        LLMPromptLog.id.in_(db.select(subq.c.id))
                    ).delete(synchronize_session=False)
                    db.session.commit()
            except Exception as e:
                logger.error(f"Failed to log LLM prompt: {e}")

    def _handle_verdict(self, watching_setup_id, signal, verdict_data):
        if not self._app:
            logger.error("Flask app context not set in LLMQueueManager")
            return

        with self._app.app_context():
            from app.models.db import db, ConfirmedSignal, WatchingSetup, RejectedSignal

            w_setup = WatchingSetup.query.get(watching_setup_id)
            if not w_setup:
                return

            v_str = verdict_data.verdict

            if v_str in ('CONFIRM', 'MODIFY'):
                w_setup.status = 'CONFIRMED'
            else:
                w_setup.status = 'REJECTED'

            sse_manager.publish('setup_updated', w_setup.to_dict())

            if v_str in ('CONFIRM', 'MODIFY'):
                db_entry = signal.entry or getattr(w_setup, 'entry', 0.0)
                db_sl = (
                    verdict_data.modified_sl
                    if v_str == 'MODIFY' and verdict_data.modified_sl
                    else getattr(w_setup, 'sl', 0.0)
                )
                db_tp1 = (
                    verdict_data.modified_tp1
                    if v_str == 'MODIFY' and verdict_data.modified_tp1
                    else getattr(w_setup, 'tp1', 0.0)
                )
                db_tp2 = (
                    verdict_data.modified_tp2
                    if v_str == 'MODIFY' and verdict_data.modified_tp2
                    else getattr(w_setup, 'tp2', 0.0)
                )

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
                    trade_outcome='ACTIVE',
                )
                db.session.add(new_sig)
                db.session.commit()

                payload = new_sig.to_dict()
                payload['session_id'] = w_setup.session_id
                sse_manager.publish('signal_confirmed', payload)
                logger.info(f"Signal CONFIRMED by LLM: {signal.symbol} {signal.strategy_name}")

                telegram_queue.enqueue_confirm_alert(new_sig.id)
                outcome_tracker.add_to_cache(new_sig)

            else:  # REJECT
                db_entry = signal.entry or getattr(w_setup, 'entry', 0.0)
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
                    reasoning_text=verdict_data.reasoning,
                )
                db.session.add(new_rejected)
                db.session.commit()
                sse_manager.publish('setup_rejected', w_setup.to_dict())
                logger.info(f"Signal REJECTED by LLM: {signal.symbol}")

                telegram_queue.enqueue_reject_alert(watching_setup_id, verdict_data.reasoning)


llm_queue = LLMQueueManager()
