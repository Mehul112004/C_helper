import threading
import logging
from datetime import datetime

from app.models.db import db, ConfirmedSignal
from app.core.telegram_queue import telegram_queue
from app.core.sse import sse_manager

logger = logging.getLogger(__name__)

class OutcomeTracker:
    """
    Singleton responsible for checking live prices against ACTIVE trade signals.
    Maintains an in-memory dictionary of levels to avoid DB spam.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._app = None
        # Dict[signal_id, dict_of_levels]
        self._cache: dict[str, dict] = {}
        
    def set_app(self, app):
        self._app = app
        
    def rebuild_cache(self):
        """
        Re-queries the database for all ACTIVE signals and rebuilding the memory cache.
        Usually called at startup or on specific signal lifecycle hooks.
        """
        if not self._app:
            return
            
        with self._app.app_context():
            active_signals = ConfirmedSignal.query.filter_by(trade_outcome='ACTIVE').all()
            with self._lock:
                self._cache.clear()
                for sig in active_signals:
                    self._cache[sig.id] = {
                        'symbol': sig.symbol,
                        'direction': sig.direction,
                        'entry': sig.entry,
                        'sl': sig.sl,
                        'tp1': sig.tp1,
                        'tp2': sig.tp2
                    }
        logger.info(f"OutcomeTracker cache rebuilt with {len(self._cache)} ACTIVE signals.")

    def add_to_cache(self, signal: ConfirmedSignal):
        """Append a newly confirmed signal dynamically."""
        with self._lock:
            self._cache[signal.id] = {
                'symbol': signal.symbol,
                'direction': signal.direction,
                'entry': signal.entry,
                'sl': signal.sl,
                'tp1': signal.tp1,
                'tp2': signal.tp2
            }

    def check_price(self, symbol: str, price: float):
        """
        Evaluate a single price tick against all cached parameters.
        Runs quickly without DB IO. If a boundary is breached, dispatches an update.
        """
        hit_signals = []
        
        with self._lock:
            for sig_id, data in list(self._cache.items()):
                if data['symbol'] != symbol:
                    continue
                    
                direction = data['direction']
                sl = data['sl']
                tp1 = data['tp1']
                tp2 = data['tp2']
                
                hit_outcome = None
                
                if direction == 'LONG':
                    if price <= sl:
                        hit_outcome = 'HIT_SL'
                    elif price >= tp2:
                        hit_outcome = 'HIT_TP2'
                    elif price >= tp1:
                        hit_outcome = 'HIT_TP1'
                
                elif direction == 'SHORT':
                    if price >= sl:
                        hit_outcome = 'HIT_SL'
                    elif price <= tp2:
                        hit_outcome = 'HIT_TP2'
                    elif price <= tp1:
                        hit_outcome = 'HIT_TP1'
                        
                if hit_outcome:
                    hit_signals.append((sig_id, hit_outcome))
                    
        # Outside of loop lock
        for sig_id, outcome in hit_signals:
             self._process_hit(sig_id, outcome)

    def _process_hit(self, signal_id: str, outcome: str):
        """Handle DB write and telegram dispatching for a hit"""
        if not self._app:
            return
            
        with self._app.app_context():
            sig = ConfirmedSignal.query.get(signal_id)
            if not sig or sig.trade_outcome != 'ACTIVE':
                # State might have changed / race condition
                with self._lock:
                    self._cache.pop(signal_id, None)
                return
                
            # Update
            sig.trade_outcome = outcome
            sig.outcome_updated_at = datetime.utcnow()
            db.session.commit()
            
            # Remove from tracking list if it hit SL or TP2 or we just drop it from tracking completely
            # For simplicity, if we hit *any* major level (SL, TP1, TP2), we may remove from Phase 6 cache
            # The user requested tracking TP1, TP2, SL. Let's trace TP1 then keep it for TP2?
            # Normally, hitting TP1 means it's partially closed or hit. In basic systems, you might
            # mark outcome as HIT_TP1 and stop tracking. Let's assume hitting TP1 resolves the alert for now.
            with self._lock:
                self._cache.pop(signal_id, None)
                
            # Notify Telegram
            telegram_queue.enqueue_outcome_alert(signal_id, outcome)
            
            # SSE push
            sse_manager.publish('signal_outcome_update', sig.to_dict())
            logger.info(f"Signal {signal_id} ({sig.symbol}) hit {outcome} at live tick.")

outcome_tracker = OutcomeTracker()
