"""
Live Analysis Scanner
Manages analysis sessions and orchestrates real-time strategy scanning.

Each session:
- Targets one symbol with selected strategies
- Opens a Binance WebSocket stream for all required timeframes
- On candle close: computes indicators, fetches S/R, runs strategies
- Pushes SSE events for watching card updates and live price ticks

Constraints: max 2 concurrent sessions, one symbol per session, ephemeral (in-memory).
"""

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.core.base_strategy import Candle
from app.core.sse import sse_manager
from app.core.strategy_runner import StrategyRunner
from app.core.watching import WatchingManager
from app.core.outcome_tracker import outcome_tracker
from app.utils.binance import BinanceStreamManager


MAX_SESSIONS = 2


@dataclass
class AnalysisSession:
    """In-memory representation of a live analysis session."""
    session_id: str
    symbol: str
    strategy_names: list[str]
    timeframes: list[str]
    created_at: datetime
    status: str = "active"  # active | stopping | stopped
    stream_manager: Optional[BinanceStreamManager] = None
    live_price: Optional[float] = None
    live_price_updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            'session_id': self.session_id,
            'symbol': self.symbol,
            'strategy_names': self.strategy_names,
            'timeframes': self.timeframes,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'live_price': self.live_price,
            'live_price_updated_at': self.live_price_updated_at.isoformat() if self.live_price_updated_at else None,
        }


class LiveScanner:
    """
    Singleton manager for all active analysis sessions.

    Responsibilities:
    - Create/destroy sessions (max 2 simultaneously)
    - On candle close: compute indicators, fetch S/R zones, run strategies
    - On setup detected: create/update WatchingSetup, push SSE event
    - On each candle close: check existing watching setups for expiry
    - On price tick: update live price, push SSE price_update event
    """

    def __init__(self, app=None):
        self._sessions: dict[str, AnalysisSession] = {}
        self._lock = threading.Lock()
        self._app = app

    def set_app(self, app):
        """Set the Flask app reference for app context in background threads."""
        self._app = app

    def start_session(self, symbol: str, strategy_names: list[str]) -> dict:
        """
        Start a new analysis session.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            strategy_names: List of strategy names to activate

        Returns:
            Session dict with session_id and metadata

        Raises:
            ValueError: If max sessions reached, duplicate symbol, or invalid strategies
        """
        symbol = symbol.upper()

        with self._lock:
            # Enforce max sessions
            active = [s for s in self._sessions.values() if s.status == "active"]
            if len(active) >= MAX_SESSIONS:
                raise ValueError(f"Maximum {MAX_SESSIONS} simultaneous sessions allowed")

            # No duplicate symbols across sessions
            for s in active:
                if s.symbol == symbol:
                    raise ValueError(f"A session for {symbol} is already active")

            # Resolve strategies and timeframes
            from app.core.strategy_loader import registry
            strategies = []
            all_timeframes = set()
            for name in strategy_names:
                strat = registry.get_by_name(name)
                if strat is None:
                    raise ValueError(f"Unknown strategy: {name}")
                strategies.append(strat)
                all_timeframes.update(strat.timeframes)

            if not strategies:
                raise ValueError("At least one strategy must be selected")

            timeframes = sorted(all_timeframes)
            session_id = str(uuid.uuid4())

            # Create the WebSocket stream manager
            stream = BinanceStreamManager(
                symbol=symbol,
                timeframes=timeframes,
                on_candle_close=lambda sym, tf, data: self._on_candle_close(session_id, sym, tf, data),
                on_price_update=lambda sym, price, ts: self._on_price_update(session_id, sym, price, ts),
            )

            session = AnalysisSession(
                session_id=session_id,
                symbol=symbol,
                strategy_names=strategy_names,
                timeframes=timeframes,
                created_at=datetime.utcnow(),
                stream_manager=stream,
            )
            self._sessions[session_id] = session

        # Persist session record to DB
        if self._app:
            with self._app.app_context():
                self._persist_session(session)

        # Start the WebSocket stream
        stream.start()

        # Publish SSE event
        session_dict = session.to_dict()
        sse_manager.publish("session_started", session_dict)
        print(f"[LiveScanner] Session started: {session_id} for {symbol} "
              f"with {strategy_names} on {timeframes}")

        return session_dict

    def stop_session(self, session_id: str) -> bool:
        """
        Stop an analysis session and clean up all resources.

        Returns:
            True if session was found and stopped, False otherwise.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.status != "active":
                return False
            session.status = "stopping"

        # Stop WebSocket
        if session.stream_manager:
            session.stream_manager.stop()

        # Expire all watching setups for this session
        if self._app:
            with self._app.app_context():
                expired_count = WatchingManager.expire_all_for_session(session_id)
                self._update_session_status(session_id, "stopped")
                print(f"[LiveScanner] Expired {expired_count} setups for session {session_id}")

        with self._lock:
            session.status = "stopped"

        sse_manager.publish("session_stopped", {"session_id": session_id})
        print(f"[LiveScanner] Session stopped: {session_id}")
        return True

    def stop_all(self):
        """Stop all active sessions. Called on app shutdown."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            self.stop_session(sid)
        print("[LiveScanner] All sessions stopped.")

    def get_active_sessions(self) -> list[dict]:
        """Return metadata for all active sessions."""
        with self._lock:
            return [
                s.to_dict() for s in self._sessions.values()
                if s.status == "active"
            ]

    def _on_candle_close(self, session_id: str, symbol: str, timeframe: str, candle_data: dict):
        """
        Core handler invoked by BinanceStreamManager when a candle closes.

        Flow:
        1. Upsert candle into DB
        2. Invalidate indicator cache
        3. Compute fresh indicators
        4. Fetch S/R zones
        5. Run strategies → create/update watching setups
        6. Tick expiry on existing setups
        """
        if not self._app:
            return

        session = self._sessions.get(session_id)
        if not session or session.status != "active":
            return

        with self._app.app_context():
            try:
                # 1. Upsert the closed candle into DB
                self._upsert_candle(candle_data)

                # 2. Invalidate indicator cache
                from app.core.indicators import IndicatorService
                IndicatorService.invalidate_cache(symbol, timeframe)

                # 3. Compute fresh indicators
                indicator_result = IndicatorService.compute_all(symbol, timeframe, include_series=True)
                if not indicator_result.get('latest'):
                    return

                # 4. Fetch S/R zones near current price
                from app.models.db import SRZone
                current_price = candle_data['close']
                price_range = current_price * 0.03  # 3%
                zones = SRZone.query.filter(
                    SRZone.symbol == symbol,
                    SRZone.price_level >= current_price - price_range,
                    SRZone.price_level <= current_price + price_range,
                ).all()
                sr_zones = [z.to_dict() for z in zones]

                # 5. Build candle window (last 50)
                from app.models.db import Candle as CandleModel
                db_candles = (
                    CandleModel.query
                    .filter_by(symbol=symbol, timeframe=timeframe)
                    .order_by(CandleModel.open_time.desc())
                    .limit(50)
                    .all()
                )
                if len(db_candles) < 10:
                    return

                candle_objects = [Candle.from_db_row(c.to_dict()) for c in reversed(db_candles)]

                # Build indicators snapshot at last index
                series = indicator_result.get('series', {})
                candle_count = indicator_result.get('candle_count', 0)
                if candle_count > 0 and series:
                    indicators = StrategyRunner.prepare_indicators_snapshot(series, candle_count - 1)
                else:
                    return

                # 6. Run strategies
                from app.core.strategy_loader import registry
                for strat_name in session.strategy_names:
                    strategy = registry.get_by_name(strat_name)
                    if not strategy or timeframe not in strategy.timeframes:
                        continue

                    signal = StrategyRunner.run_single_scan(
                        strategy=strategy,
                        symbol=symbol,
                        timeframe=timeframe,
                        candles=candle_objects,
                        indicators=indicators,
                        sr_zones=sr_zones,
                    )

                    if signal:
                        setup_dict, is_new = WatchingManager.create_or_update_setup(session_id, signal)
                        event_type = "setup_detected" if is_new else "setup_updated"
                        sse_manager.publish(event_type, setup_dict)

                        if is_new:
                            from app.core.llm_queue import llm_queue
                            if hasattr(strategy, 'should_confirm_with_llm') and strategy.should_confirm_with_llm(signal):
                                llm_queue.enqueue_signal(
                                    watching_setup_id=setup_dict['id'],
                                    signal=signal,
                                    candles=candle_objects,
                                    indicators=indicators,
                                    sr_zones=sr_zones
                                )

                # 7. Tick expiry on existing setups
                expired = WatchingManager.tick_candle_close(session_id, symbol, timeframe)
                for exp in expired:
                    sse_manager.publish("setup_expired", exp)

                # Publish candle close event
                sse_manager.publish("candle_close", {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "close": candle_data['close'],
                    "timestamp": candle_data['open_time'].isoformat() if hasattr(candle_data['open_time'], 'isoformat') else str(candle_data['open_time']),
                })

            except Exception as e:
                print(f"[LiveScanner] Error in candle close handler: {e}")

    def _on_price_update(self, session_id: str, symbol: str, price: float, timestamp):
        """Handle live price tick from unclosed candle."""
        session = self._sessions.get(session_id)
        if not session or session.status != "active":
            return

        session.live_price = price
        session.live_price_updated_at = timestamp
        
        # Check against active trade limits
        outcome_tracker.check_price(symbol, price)

        sse_manager.publish("price_update", {
            "session_id": session_id,
            "symbol": symbol,
            "price": price,
            "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
        })

    def _upsert_candle(self, candle_data: dict):
        """Upsert a closed candle into the database."""
        from app.models.db import db, Candle as CandleModel
        from sqlalchemy.dialects.postgresql import insert

        try:
            # Try PostgreSQL upsert first
            stmt = insert(CandleModel).values(
                symbol=candle_data['symbol'],
                timeframe=candle_data['timeframe'],
                open_time=candle_data['open_time'],
                open=candle_data['open'],
                high=candle_data['high'],
                low=candle_data['low'],
                close=candle_data['close'],
                volume=candle_data['volume'],
            )
            do_upsert = stmt.on_conflict_do_update(
                index_elements=['symbol', 'timeframe', 'open_time'],
                set_={
                    'open': stmt.excluded.open,
                    'high': stmt.excluded.high,
                    'low': stmt.excluded.low,
                    'close': stmt.excluded.close,
                    'volume': stmt.excluded.volume,
                }
            )
            db.session.execute(do_upsert)
            db.session.commit()
        except Exception:
            db.session.rollback()
            # Fallback: simple merge for SQLite/testing
            try:
                existing = CandleModel.query.filter_by(
                    symbol=candle_data['symbol'],
                    timeframe=candle_data['timeframe'],
                    open_time=candle_data['open_time'],
                ).first()
                if existing:
                    existing.open = candle_data['open']
                    existing.high = candle_data['high']
                    existing.low = candle_data['low']
                    existing.close = candle_data['close']
                    existing.volume = candle_data['volume']
                else:
                    db.session.add(CandleModel(**{
                        k: v for k, v in candle_data.items()
                        if k in ('symbol', 'timeframe', 'open_time', 'open', 'high', 'low', 'close', 'volume')
                    }))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[LiveScanner] Candle upsert fallback error: {e}")

    def _persist_session(self, session: AnalysisSession):
        """Save session record to DB."""
        from app.models.db import db, AnalysisSessionRecord
        record = AnalysisSessionRecord(
            id=session.session_id,
            symbol=session.symbol,
            strategy_names=json.dumps(session.strategy_names),
            timeframes=json.dumps(session.timeframes),
            status='active',
        )
        db.session.add(record)
        db.session.commit()

    def _update_session_status(self, session_id: str, status: str):
        """Update session status in DB."""
        from app.models.db import db, AnalysisSessionRecord
        record = AnalysisSessionRecord.query.get(session_id)
        if record:
            record.status = status
            if status == "stopped":
                record.stopped_at = datetime.utcnow()
            db.session.commit()


# Module-level singleton
live_scanner = LiveScanner()
