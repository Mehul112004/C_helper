import queue
import threading
import time
import logging
from typing import Tuple

from app.core.telegram_client import telegram_client
from app.core.telegram_formatter import format_confirmed_signal, format_outcome_update
from app.models.db import db, ConfirmedSignal

logger = logging.getLogger(__name__)

# Queue payload types
# Msg: (signal_id, alert_type, outcome_val)
# alert_type: 'CONFIRM' or 'OUTCOME'
QueuePayload = Tuple[str, str, str | None]

class TelegramDeliveryManager:
    """
    Background worker that processes Telegram message deliveries.
    Handles retries up to 3 times on network failure.
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
            self._worker_thread = threading.Thread(target=self._run_worker, daemon=True, name="TelegramWorker")
            self._worker_thread.start()
            logger.info("Telegram background worker started.")

    def stop(self):
        self._stop_event.set()
        if self._worker_thread:
            self._q.put(None)
            self._worker_thread.join(timeout=2)
            logger.info("Telegram background worker stopped.")

    def enqueue_confirm_alert(self, signal_id: str):
        self._q.put((signal_id, 'CONFIRM', None))
        
    def enqueue_outcome_alert(self, signal_id: str, outcome: str):
        self._q.put((signal_id, 'OUTCOME', outcome))

    def _run_worker(self):
        while not self._stop_event.is_set():
            try:
                item = self._q.get(timeout=1)
                if item is None:
                    continue  # Stop signal
                    
                signal_id, alert_type, outcome_val = item
                
                # Retrieve signal inside app context
                if not self._app:
                     continue
                     
                with self._app.app_context():
                    signal = ConfirmedSignal.query.get(signal_id)
                    if not signal:
                        logger.error(f"Signal {signal_id} not found for TG delivery")
                        continue
                        
                    # Skip if Telegram not configured
                    if not telegram_client.is_configured():
                         continue
                    
                    # Prevent resending on CONFIRM
                    if alert_type == 'CONFIRM' and signal.telegram_status == 'SENT':
                        continue
                        
                    # Format text
                    if alert_type == 'CONFIRM':
                        text = format_confirmed_signal(signal)
                        reply_to = None
                    else:
                        text = format_outcome_update(signal, outcome_val)
                        reply_to = signal.telegram_message_id
                        
                    response = telegram_client.send_message(text, reply_to_message_id=reply_to)
                    
                    if response:
                        message_id = str(response.get("result", {}).get("message_id"))
                        signal.telegram_status = 'SENT'
                        signal.telegram_retries = 0
                        if alert_type == 'CONFIRM' and message_id != "None":
                            signal.telegram_message_id = message_id
                        db.session.commit()
                        logger.info(f"Telegram notice delivered for signal {signal_id}")
                    else:
                        # Fail / retry handling
                        if alert_type == 'CONFIRM': # We only implement strict retry for primary signal
                            signal.telegram_retries += 1
                            if signal.telegram_retries >= 3:
                                signal.telegram_status = 'FAILED'
                                db.session.commit()
                                logger.error(f"Telegram failed max retries for signal {signal_id}")
                            else:
                                db.session.commit()
                                logger.warning(f"Telegram retry {signal.telegram_retries}/3 for {signal_id}. Re-queueing in 10s.")
                                time.sleep(10)
                                self._q.put(item)
                        else:
                            # Don't strictly retry outcome messages as they are secondary
                            logger.error(f"Failed to send outcome update for {signal_id}.")
                            
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in Telegram queue worker: {e}")
                time.sleep(5)

telegram_queue = TelegramDeliveryManager()
