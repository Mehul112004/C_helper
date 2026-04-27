"""
Live Analysis Scanner
Manages analysis sessions and orchestrates real-time strategy scanning.

Each session:
- Targets one symbol with selected strategies
- Opens a Binance WebSocket stream for all required timeframes
- On candle close: computes indicators, fetches S/R, runs strategies
- Pushes SSE events for watching card updates and live price ticks

Constraints: max 10 concurrent sessions, one symbol per session, ephemeral (in-memory).
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.base_strategy import Candle
from app.core.sse import sse_manager
from app.core.strategy_runner import StrategyRunner
from app.core.watching import WatchingManager
from app.core.outcome_tracker import outcome_tracker
from app.utils.binance import BinanceStreamManager, fetch_klines
from app.core.config import CANDLE_WARMUP

logger = logging.getLogger(__name__)

# Timeframe → duration in minutes (for backfill calculations)
TIMEFRAME_MINUTES = {
    '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
    '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480,
    '12h': 720, '1d': 1440, '3d': 4320, '1w': 10080,
}

# Timeframe → duration in milliseconds (for gap detection arithmetic)
TIMEFRAME_MS = {k: v * 60 * 1000 for k, v in TIMEFRAME_MINUTES.items()}

# Minimum candles needed for indicator warm-up (EMA 200 + buffer)
MIN_BACKFILL_CANDLES = CANDLE_WARMUP


MAX_SESSIONS = 10


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
    - Create/destroy sessions (max 10 simultaneously)
    - On candle close: compute indicators, fetch S/R zones, run strategies
    - On setup detected: create/update WatchingSetup, push SSE event
    - On each candle close: check existing watching setups for expiry
    - On price tick: update live price, push SSE price_update event
    """

    def __init__(self, app=None):
        self._sessions: dict[str, AnalysisSession] = {}
        self._lock = threading.Lock()
        self._app = app
        self._live_candle_throttle: dict[str, float] = {}  # key → last_emit_ts

    def set_app(self, app):
        """Set the Flask app reference for app context in background threads."""
        self._app = app

    def start_session(self, symbol: str, strategy_names: list[str], selected_timeframes: list[str] = None) -> dict:
        """
        Start a new analysis session.

        Includes cold start protection:
        - Backfills historical candle data via REST API if insufficient in DB
        - Generates S/R zones on-demand if none exist for the symbol

        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            strategy_names: List of strategy names to activate
            selected_timeframes: Optional list of timeframes to restrict to

        Returns:
            Session dict with session_id and metadata

        Raises:
            ValueError: If max sessions reached, duplicate symbol, or invalid strategies
        """
        symbol = symbol.upper()

        # Resolve strategies and timeframes
        from app.core.strategy_loader import registry
        strategies = []
        all_timeframes = set()
        for name in strategy_names:
            strat = registry.get_by_name(name)
            if strat is None:
                raise ValueError(f"Unknown strategy: {name}")
            strategies.append(strat)
            if not selected_timeframes:
                all_timeframes.update(strat.timeframes)

        if not strategies:
            raise ValueError("At least one strategy must be selected")

        if selected_timeframes:
            timeframes = list(set(selected_timeframes))
        else:
            timeframes = sorted(all_timeframes)

        with self._lock:
            # Enforce max sessions
            active = [s for s in self._sessions.values() if s.status == "active"]
            if len(active) >= MAX_SESSIONS:
                raise ValueError(f"Maximum {MAX_SESSIONS} simultaneous sessions allowed")

            # No duplicate symbols across sessions
            live = [s for s in self._sessions.values() if s.status in ("active", "stopping")]
            for s in live:
                if s.symbol == symbol:
                    raise ValueError(f"A session for {symbol} is already active")
                
            session_id = str(uuid.uuid4())

            # Create the WebSocket stream manager
            stream = BinanceStreamManager(
                symbol=symbol,
                timeframes=timeframes,
                on_candle_close=lambda sym, tf, data: self._on_candle_close(session_id, sym, tf, data),
                on_price_update=lambda sym, price, ts: self._on_price_update(session_id, sym, price, ts),
                on_live_candle=lambda sym, tf, data: self._on_live_candle(session_id, sym, tf, data),
                on_reconnect=lambda sym: self._on_ws_reconnect(session_id, sym),
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

        # Publish SSE event
        session_dict = session.to_dict()
        sse_manager.publish("session_started", session_dict)

        def _background_start():
            try:
                # --- Cold Start Protection (runs before WebSocket connects) ---
                if self._app:
                    with self._app.app_context():
                        self._persist_session(session)
                        self._backfill_historical_data(symbol, timeframes)
                        self._ensure_sr_zones(symbol, timeframes)
            except Exception as e:
                logger.error(f"[LiveScanner] Background start failed for {session_id}: {e}")
            finally:
                # Start the WebSocket stream (AFTER backfill is done, or even if it fails)
                stream.start()
                logger.info(f"[LiveScanner] Session fully started: {session_id} for {symbol} "
                             f"with {strategy_names} on {timeframes}")

        thread = threading.Thread(target=_background_start, daemon=True)
        thread.start()

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
        7. Tick expiry on existing watching setups
        """
        if not self._app:
            return

        with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.status != "active":
                return

        with self._app.app_context():
            from app.core.indicators import IndicatorService
            from app.models.db import SRZone, Candle as CandleModel
            from app.core.strategy_loader import registry
            from app.core.telegram_queue import telegram_queue
            from app.core.llm_queue import llm_queue

            try:
                print(f"[LiveScanner] ── Candle close: {symbol}/{timeframe} "
                      f"close={candle_data['close']:.2f} vol={candle_data['volume']:.2f}")

                # 1. Upsert the closed candle into DB
                self._upsert_candle(candle_data)

                # 1b. Gap detection & auto-heal
                #     Must run AFTER upsert (incoming candle is valid data)
                #     but BEFORE indicators (they need contiguous data)
                gap_healed = self._detect_and_heal_gap(
                    symbol, timeframe, candle_data['open_time']
                )

                # 2. Invalidate indicator cache
                #    Always invalidate — covers both normal and healed paths
                IndicatorService.invalidate_cache(symbol, timeframe)

                # 2b. Trigger S/R zone refresh based on candle timeframe (FIX-SR-1)
                from app.core.sr_engine import SREngine
                if timeframe in ('4h', '1d'):
                    SREngine.full_refresh(symbol, timeframe)
                elif timeframe in ('1h', '15m'):
                    SREngine.minor_update(symbol, timeframe)

                # 3. Compute fresh indicators
                indicator_result = IndicatorService.compute_all(symbol, timeframe, include_series=True)
                if not indicator_result.get('latest'):
                    print(f"[LiveScanner]    ⚠ No indicator data for {symbol}/{timeframe}")
                    return

                # 4. Fetch S/R zones near current price (under refresh lock — FIX-SCH-3)
                current_price = candle_data['close']
                price_range = current_price * 0.03  # 3%
                with SREngine.get_refresh_lock(symbol):
                    zones = SRZone.query.filter(
                        SRZone.symbol == symbol,
                        SRZone.price_level >= current_price - price_range,
                        SRZone.price_level <= current_price + price_range,
                    ).all()
                    sr_zones = [z.to_dict() for z in zones]

                # 5. Build candle window (last 50)
                db_candles = (
                    CandleModel.query
                    .filter_by(symbol=symbol, timeframe=timeframe)
                    .order_by(CandleModel.open_time.desc())
                    .limit(50)
                    .all()
                )
                if len(db_candles) < 10:
                    print(f"[LiveScanner]    ⚠ Only {len(db_candles)} candles in DB for "
                          f"{symbol}/{timeframe} (need ≥10)")
                    return

                candle_objects = [Candle.from_db_row(c.to_dict()) for c in reversed(db_candles)]

                # Build indicators snapshot at last index
                series = indicator_result.get('series', {})
                candle_count = indicator_result.get('candle_count', 0)
                if candle_count > 0 and series:
                    indicators = StrategyRunner.prepare_indicators_snapshot(series, candle_count - 1)
                else:
                    print(f"[LiveScanner]    ⚠ No series data (candle_count={candle_count})")
                    return

                # Debug: log indicator availability
                ind_status = []
                if indicators.rsi_14 is not None:
                    ind_status.append(f"RSI={indicators.rsi_14:.1f}")
                else:
                    ind_status.append("RSI=None")
                if indicators.atr_14 is not None:
                    ind_status.append(f"ATR={indicators.atr_14:.4f}")
                else:
                    ind_status.append("ATR=None")
                if indicators.bb_width is not None:
                    ind_status.append(f"BBW={indicators.bb_width:.6f}")
                else:
                    ind_status.append("BBW=None")
                if indicators.volume_ma_20 is not None:
                    ind_status.append(f"VolMA={indicators.volume_ma_20:.0f}")
                else:
                    ind_status.append("VolMA=None")
                print(f"[LiveScanner]    Indicators ({candle_count} candles): {', '.join(ind_status)}")
                print(f"[LiveScanner]    S/R zones in range: {len(sr_zones)}")

                # 6. Fetch HTF context
                htf_candles = self._fetch_htf_candles(symbol, timeframe)

                # 7. Run strategies
                signals_found = 0
                for strat_name in session.strategy_names:
                    strategy = registry.get_by_name(strat_name)
                    if not strategy:
                        continue
                    if timeframe not in strategy.timeframes:
                        continue

                    signal = StrategyRunner.run_single_scan(
                        strategy=strategy,
                        symbol=symbol,
                        timeframe=timeframe,
                        candles=candle_objects,
                        indicators=indicators,
                        sr_zones=sr_zones,
                        htf_candles=htf_candles,
                    )

                    if signal:
                        signals_found += 1
                        print(f"[LiveScanner]    ✅ SIGNAL: {strat_name} → {signal.direction} "
                              f"conf={signal.confidence:.2f}")
                        setup_dict, is_new = WatchingManager.create_or_update_setup(session_id, signal)
                        event_type = "setup_detected" if is_new else "setup_updated"
                        sse_manager.publish(event_type, setup_dict)

                        if is_new:
                            telegram_queue.enqueue_watching_alert(setup_dict['id'])
                            
                            if hasattr(strategy, 'should_confirm_with_llm') and strategy.should_confirm_with_llm(signal):
                                llm_queue.enqueue_signal(
                                    watching_setup_id=setup_dict['id'],
                                    signal=signal,
                                    candles=candle_objects,
                                    indicators=indicators,
                                    sr_zones=sr_zones,
                                    htf_candles=htf_candles
                                )

                if signals_found == 0:
                    strats_checked = [s for s in session.strategy_names
                                      if registry.get_by_name(s) and timeframe in registry.get_by_name(s).timeframes]
                    print(f"[LiveScanner]    ── No signals from {len(strats_checked)} strategies on {timeframe}")

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
                import traceback
                print(f"[LiveScanner] Error in candle close handler: {e}")
                traceback.print_exc()

    def _on_price_update(self, session_id: str, symbol: str, price: float, timestamp):
        """Handle live price tick from unclosed candle."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.status != "active":
                return

            session.live_price = price
            session.live_price_updated_at = timestamp
        
        # Check against active trade limits
        try:
            outcome_tracker.check_price(symbol, price)
        except Exception as e:
            logger.error(f"[LiveScanner] Error tracking outcome for {symbol}: {e}")

        sse_manager.publish("price_update", {
            "session_id": session_id,
            "symbol": symbol,
            "price": price,
            "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
        })

    def _on_live_candle(self, session_id: str, symbol: str, timeframe: str, candle_data: dict):
        """
        Handle every kline tick (open and in-progress candles).
        Throttled to max 1 emit per 500ms per symbol/timeframe pair.
        Always emits immediately for is_closed=True (candle finalization).

        Also persists the live candle to DB every ~5s so that the chart
        REST endpoint always includes the currently open candle.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.status != "active":
                return

        # Throttle: skip if we emitted less than 500ms ago (unless candle just closed)
        throttle_key = f"{symbol}_{timeframe}"
        now = time.time()
        if not candle_data.get("is_closed", False):
            last_emit = self._live_candle_throttle.get(throttle_key, 0)
            if now - last_emit < 0.5:
                return
        self._live_candle_throttle[throttle_key] = now

        # ── Persist live candle to DB (throttled to every ~5s) ──
        # This ensures GET /api/data/candles always returns the open candle.
        if self._app:
            persist_key = f"db_{symbol}_{timeframe}"
            last_persist = self._live_candle_throttle.get(persist_key, 0)
            if now - last_persist >= 5.0 or candle_data.get("is_closed", False):
                self._live_candle_throttle[persist_key] = now
                try:
                    with self._app.app_context():
                        self._upsert_candle({
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'open_time': datetime.fromtimestamp(
                                candle_data['open_time'] / 1000.0,
                                tz=timezone.utc,
                            ),
                            'open': candle_data['open'],
                            'high': candle_data['high'],
                            'low': candle_data['low'],
                            'close': candle_data['close'],
                            'volume': candle_data['volume'],
                        })
                except Exception as e:
                    logger.error(f"[LiveScanner] Live candle DB persist error: {e}")

        sse_manager.publish("live_candle", {
            "session_id": session_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": candle_data["open_time"],      # ms int
            "close_time": candle_data["close_time"],    # ms int
            "open": candle_data["open"],
            "high": candle_data["high"],
            "low": candle_data["low"],
            "close": candle_data["close"],
            "volume": candle_data["volume"],
            "is_closed": candle_data["is_closed"],
        })

    def _backfill_historical_data(self, symbol: str, timeframes: list[str]):
        """
        Pre-flight data backfill: fetch historical candles via Binance REST API.

        Two modes:
        1. Cold start: DB has fewer than MIN_BACKFILL_CANDLES → full historical fetch.
        2. Top-up: DB has enough candles but may have a gap from backend downtime →
           fetch from last stored candle to now to fill any restart gaps immediately.

        This ensures indicators have warm-up data AND the chart never has holes
        after a backend restart.
        """
        from app.models.db import Candle as CandleModel, db

        for tf in timeframes:
            existing_count = CandleModel.query.filter_by(
                symbol=symbol, timeframe=tf
            ).count()

            tf_minutes = TIMEFRAME_MINUTES.get(tf, 60)
            now_ms = int(time.time() * 1000)

            if existing_count >= MIN_BACKFILL_CANDLES:
                # ── Top-up mode: fill gap from last stored candle to now ──
                last_candle = (
                    CandleModel.query
                    .filter_by(symbol=symbol, timeframe=tf)
                    .order_by(CandleModel.open_time.desc())
                    .first()
                )
                if last_candle:
                    last_open_ms = int(last_candle.open_time.timestamp() * 1000)
                    # Start from one candle period after the last stored candle
                    gap_start_ms = last_open_ms + (tf_minutes * 60 * 1000)

                    if gap_start_ms >= now_ms:
                        logger.info(f"[LiveScanner] Backfill skip: {symbol}/{tf} is up-to-date "
                                    f"({existing_count} candles)")
                        continue

                    logger.info(f"[LiveScanner] Top-up backfill: {symbol}/{tf} — "
                                f"fetching gap from {last_candle.open_time.isoformat()} to now...")
                    try:
                        candles = fetch_klines(symbol, tf, gap_start_ms, now_ms)
                        if candles:
                            upserted = 0
                            skipped = 0
                            for candle_data in candles:
                                # Guard: skip the unclosed candle Binance appends
                                expected_close = candle_data['open_time'] + timedelta(minutes=tf_minutes)
                                if expected_close > datetime.now(timezone.utc):
                                    skipped += 1
                                    logger.info(
                                        f"[LiveScanner] ⏭ Skipping unclosed candle: {symbol}/{tf} "
                                        f"open_time={candle_data['open_time'].isoformat()}"
                                    )
                                    continue
                                self._upsert_candle(candle_data, commit=False)
                                upserted += 1
                            db.session.commit()
                            logger.info(f"[LiveScanner] ✅ Top-up complete: {symbol}/{tf} — "
                                        f"upserted {upserted} candles"
                                        f"{f', skipped {skipped} unclosed' if skipped else ''}")
                        else:
                            logger.info(f"[LiveScanner] Top-up: no new candles for {symbol}/{tf}")
                    except Exception as e:
                        logger.error(f"[LiveScanner] Top-up backfill failed for {symbol}/{tf}: {e}")
                continue

            # ── Cold start mode: full historical fetch ──
            logger.info(f"[LiveScanner] Backfilling {symbol}/{tf}: have {existing_count}, "
                        f"fetching ~{MIN_BACKFILL_CANDLES} candles via REST API...")

            try:
                # Fetch extra to account for gaps/weekends
                lookback_minutes = MIN_BACKFILL_CANDLES * tf_minutes * 1.2
                start_ms = now_ms - int(lookback_minutes * 60 * 1000)

                candles = fetch_klines(symbol, tf, start_ms, now_ms)

                if not candles:
                    logger.warning(f"[LiveScanner] No historical data returned for {symbol}/{tf}")
                    continue

                # Bulk upsert the fetched candles
                upserted = 0
                skipped = 0
                for candle_data in candles:
                    # Guard: skip the unclosed candle Binance appends
                    expected_close = candle_data['open_time'] + timedelta(minutes=tf_minutes)
                    if expected_close > datetime.now(timezone.utc):
                        skipped += 1
                        logger.info(
                            f"[LiveScanner] ⏭ Skipping unclosed candle: {symbol}/{tf} "
                            f"open_time={candle_data['open_time'].isoformat()}"
                        )
                        continue
                    self._upsert_candle(candle_data, commit=False)
                    upserted += 1

                db.session.commit()

                logger.info(f"[LiveScanner] ✅ Backfill complete: {symbol}/{tf} — "
                            f"upserted {upserted} candles"
                            f"{f', skipped {skipped} unclosed' if skipped else ''}")

            except Exception as e:
                logger.error(f"[LiveScanner] Backfill failed for {symbol}/{tf}: {e}")
                # Don't abort session — partial data is better than none

    def _ensure_sr_zones(self, symbol: str, timeframes: list[str]):
        """
        On-demand S/R zone generation: if no zones exist for a symbol/timeframe,
        trigger SREngine.full_refresh() synchronously so S/R-based strategies
        work immediately instead of waiting for the 4-hour scheduler.
        """
        from app.models.db import SRZone
        from app.core.sr_engine import SREngine

        logger.info(f"[LiveScanner] Checking S/R zones for {symbol}...")

        # Generate zones for each timeframe that has enough data
        for tf in timeframes:
            has_zones = SRZone.query.filter_by(symbol=symbol, timeframe=tf).first()
            if not has_zones:
                try:
                    logger.info(f"[LiveScanner] No S/R zones found for {symbol}/{tf}. Generating now...")
                    SREngine.full_refresh(symbol, tf)
                    zone_count = SRZone.query.filter_by(symbol=symbol, timeframe=tf).count()
                    logger.info(f"[LiveScanner] ✅ Generated {zone_count} S/R zones for {symbol}/{tf}")
                except Exception as e:
                    logger.error(f"[LiveScanner] S/R zone generation failed for {symbol}/{tf}: {e}")
            else:
                logger.info(f"[LiveScanner] S/R zones exist for {symbol}/{tf}, skipping on-demand generation")

    def _upsert_candle(self, candle_data: dict, commit: bool = True):
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
            if commit:
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
                if commit:
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[LiveScanner] Candle upsert fallback error: {e}")

    def _detect_and_heal_gap(
        self, symbol: str, timeframe: str, incoming_open_time: datetime
    ) -> bool:
        """
        Compare incoming candle's open_time against the last stored candle
        for this symbol/timeframe. If a temporal gap is detected, backfill
        the missing candles via the Binance REST API.

        This is the core defence against dropped candles during WS reconnects
        and REST-to-WS transitions. Without this, recursive indicators (EMA,
        MACD, RSI) compute over discontinuous data and produce invalid values.

        Returns:
            True if a gap was detected and healed (caller should recalculate).
            False if no gap — normal flow continues.
        """
        from app.models.db import db, Candle as CandleModel

        tf_ms = TIMEFRAME_MS.get(timeframe)
        if tf_ms is None:
            logger.warning(
                f"[GapDetect] Unknown timeframe '{timeframe}' — "
                f"skipping gap detection for {symbol}"
            )
            return False

        # Query the most recent candle BEFORE the incoming one
        last_candle = (
            CandleModel.query
            .filter(
                CandleModel.symbol == symbol,
                CandleModel.timeframe == timeframe,
                CandleModel.open_time < incoming_open_time,
            )
            .order_by(CandleModel.open_time.desc())
            .first()
        )

        if last_candle is None:
            # No previous candle — cold start, nothing to compare against
            return False

        # Calculate expected next candle open_time
        expected_next_open = last_candle.open_time + timedelta(
            milliseconds=tf_ms
        )

        # Allow 500ms tolerance for timestamp jitter
        tolerance = timedelta(milliseconds=500)
        if incoming_open_time <= expected_next_open + tolerance:
            # No gap — contiguous data
            return False

        # ── Gap detected ──
        gap_delta = incoming_open_time - expected_next_open
        missing_candles_est = int(gap_delta.total_seconds() * 1000 / tf_ms)

        logger.warning(
            f"[GapDetect] ⚠ GAP DETECTED: {symbol}/{timeframe} — "
            f"last_stored={last_candle.open_time.isoformat()} "
            f"incoming={incoming_open_time.isoformat()} "
            f"expected_next={expected_next_open.isoformat()} "
            f"gap_delta={gap_delta} "
            f"missing_candles≈{missing_candles_est}"
        )

        # Convert to ms timestamps for REST API
        expected_open_ms = int(expected_next_open.timestamp() * 1000)
        # Fetch up to (but not including) the incoming candle — it's already upserted
        incoming_open_ms = int(incoming_open_time.timestamp() * 1000) - 1

        try:
            backfill_candles = fetch_klines(
                symbol, timeframe, expected_open_ms, incoming_open_ms
            )

            if not backfill_candles:
                logger.error(
                    f"[GapHeal] REST API returned 0 candles for gap backfill "
                    f"{symbol}/{timeframe} "
                    f"[{expected_next_open.isoformat()} → {incoming_open_time.isoformat()}]"
                )
                return False

            # Insert backfilled candles sequentially
            healed_count = 0
            for candle_data in backfill_candles:
                self._upsert_candle(candle_data, commit=False)
                healed_count += 1

            db.session.commit()

            logger.info(
                f"[GapHeal] ✅ Gap healed: {symbol}/{timeframe} — "
                f"backfilled {healed_count} candles "
                f"[{expected_next_open.isoformat()} → {incoming_open_time.isoformat()}]"
            )
            return True

        except Exception as e:
            db.session.rollback()
            logger.error(
                f"[GapHeal] Backfill FAILED for {symbol}/{timeframe}: {e}"
            )
            return False

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

    def _fetch_htf_candles(self, symbol: str, timeframe: str) -> Optional[list[Candle]]:
        """Fetch Higher Timeframe (HTF) context for the LLM prompt."""
        from app.models.db import Candle as CandleModel
        
        DEFAULT_HTF_MAP = {
            '1m': '5m',
            '3m': '15m',
            '5m': '15m',
            '15m': '1h',
            '30m': '4h',
            '1h': '4h',
            '2h': '4h',
            '4h': '1d',
            '6h': '1d',
            '8h': '1d',
            '12h': '1d',
            '1d': '1w'
        }
        
        htf = DEFAULT_HTF_MAP.get(timeframe)
        if not htf:
            return None
            
        try:
            db_candles = (
                CandleModel.query
                .filter_by(symbol=symbol, timeframe=htf)
                .order_by(CandleModel.open_time.desc())
                .limit(10)
                .all()
            )
            if not db_candles:
                return None
                
            return [Candle.from_db_row(c.to_dict()) for c in reversed(db_candles)]
        except Exception as e:
            logger.error(f"Error fetching HTF candles for {symbol}/{timeframe} -> {htf}: {e}")
            return None

    def _on_ws_reconnect(self, session_id: str, symbol: str):
        """
        Fired when BinanceStreamManager reconnects after a drop.
        Immediately backfills any missing candles for all timeframes
        in the session so gap healing doesn't wait for the next candle close.
        """
        if not self._app:
            return

        with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.status != "active":
                return
            timeframes = list(session.timeframes)

        logger.warning(
            f"[LiveScanner] ⚡ WebSocket RECONNECTED for {symbol}. "
            f"Triggering immediate gap backfill for {timeframes}..."
        )

        with self._app.app_context():
            self._backfill_historical_data(symbol, timeframes)
            # Invalidate indicator caches so next candle_close
            # recomputes from the healed data
            from app.core.indicators import IndicatorService
            for tf in timeframes:
                IndicatorService.invalidate_cache(symbol, tf)

        logger.info(
            f"[LiveScanner] ✅ Reconnect backfill complete for {symbol}/{timeframes}"
        )


# Module-level singleton
live_scanner = LiveScanner()
