"""
Watching Setup Lifecycle Manager
Manages the creation, deduplication, expiry, and querying of WatchingSetup records.

Lifecycle:
  Strategy fires → create_or_update_setup() → WATCHING
  Same strategy re-fires → update existing (reset expiry counter)
  Candle closes → tick_candle_close() → increment counter
  Counter reaches expiry_candles → mark EXPIRED
  Session stops → expire_all_for_session()
"""

import os
import uuid
from datetime import datetime

from app.models.db import db, WatchingSetup


class WatchingManager:
    """
    Manages the lifecycle of WatchingSetup records.

    Key responsibilities:
    - Create setups from SetupSignal objects with deduplication
    - Track candle closes per setup for expiry logic
    - Expire setups that exceed their candle close threshold
    - Provide query APIs for active setups
    """

    @staticmethod
    def _get_expiry_candles() -> int:
        """Get the default expiry threshold from environment."""
        return int(os.environ.get('SIGNAL_EXPIRY_CANDLES', 3))

    @classmethod
    def create_or_update_setup(cls, session_id: str, signal) -> tuple[dict, bool]:
        """
        Create a new WatchingSetup or update an existing one (deduplication).

        Dedup key: session_id + strategy_name + symbol + timeframe (all WATCHING status).
        On match: updates confidence, notes, entry, SL/TP, resets candles_since_detected.
        On no match: creates a new record.

        Args:
            session_id: UUID of the active analysis session
            signal: SetupSignal dataclass from strategy scan

        Returns:
            Tuple of (setup_dict, is_new) where is_new indicates if a new record was created.
        """
        # Check for existing WATCHING setup with same dedup key
        existing = WatchingSetup.query.filter_by(
            session_id=session_id,
            strategy_name=signal.strategy_name,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            status='WATCHING',
        ).first()

        if existing:
            # Dedup: update the existing setup
            existing.confidence = signal.confidence
            existing.notes = signal.notes
            existing.entry = signal.entry
            existing.sl = signal.sl
            existing.tp1 = signal.tp1
            existing.tp2 = signal.tp2
            existing.direction = signal.direction
            existing.candles_since_detected = 0  # Reset expiry counter
            db.session.commit()
            return existing.to_dict(), False
        else:
            # Create new watching setup
            setup = WatchingSetup(
                id=str(uuid.uuid4()),
                session_id=session_id,
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                direction=signal.direction,
                strategy_name=signal.strategy_name,
                confidence=signal.confidence,
                entry=signal.entry,
                sl=signal.sl,
                tp1=signal.tp1,
                tp2=signal.tp2,
                notes=signal.notes or '',
                status='WATCHING',
                candles_since_detected=0,
                expiry_candles=cls._get_expiry_candles(),
                zone_description='',
                condition_description='',
            )
            db.session.add(setup)
            db.session.commit()
            return setup.to_dict(), True

    @staticmethod
    def tick_candle_close(session_id: str, symbol: str, timeframe: str) -> list[dict]:
        """
        Called on each candle close. Increments candles_since_detected for all
        WATCHING setups matching the session/symbol/timeframe, and marks any
        that have exceeded their expiry threshold.

        Args:
            session_id: UUID of the analysis session
            symbol: Trading pair that closed
            timeframe: Timeframe of the closed candle

        Returns:
            List of setup dicts that were just expired.
        """
        watching = WatchingSetup.query.filter_by(
            session_id=session_id,
            symbol=symbol,
            timeframe=timeframe,
            status='WATCHING',
        ).all()

        expired = []
        for setup in watching:
            setup.candles_since_detected += 1
            if setup.candles_since_detected >= setup.expiry_candles:
                setup.status = 'EXPIRED'
                setup.expired_at = datetime.utcnow()
                expired.append(setup.to_dict())

        db.session.commit()
        return expired

    @staticmethod
    def get_active_setups(session_id: str = None) -> list[dict]:
        """
        Query all WATCHING setups, optionally filtered by session.

        Args:
            session_id: If provided, only return setups for this session.

        Returns:
            List of setup dicts with status == 'WATCHING'.
        """
        query = WatchingSetup.query.filter_by(status='WATCHING')
        if session_id:
            query = query.filter_by(session_id=session_id)

        setups = query.order_by(WatchingSetup.detected_at.desc()).all()
        return [s.to_dict() for s in setups]

    @staticmethod
    def expire_setup(setup_id: str) -> dict | None:
        """
        Manually expire a specific watching setup.

        Args:
            setup_id: UUID of the setup to expire.

        Returns:
            Updated setup dict, or None if not found.
        """
        setup = WatchingSetup.query.get(setup_id)
        if not setup or setup.status != 'WATCHING':
            return None

        setup.status = 'EXPIRED'
        setup.expired_at = datetime.utcnow()
        db.session.commit()
        return setup.to_dict()

    @staticmethod
    def expire_all_for_session(session_id: str) -> int:
        """
        Expire all WATCHING setups for a given session.
        Called when a session is stopped.

        Args:
            session_id: UUID of the session being stopped.

        Returns:
            Number of setups expired.
        """
        watching = WatchingSetup.query.filter_by(
            session_id=session_id,
            status='WATCHING',
        ).all()

        now = datetime.utcnow()
        for setup in watching:
            setup.status = 'EXPIRED'
            setup.expired_at = now

        db.session.commit()
        return len(watching)

    @staticmethod
    def get_setup(setup_id: str) -> dict | None:
        """
        Get a specific watching setup by ID.

        Args:
            setup_id: UUID of the setup.

        Returns:
            Setup dict or None if not found.
        """
        setup = WatchingSetup.query.get(setup_id)
        return setup.to_dict() if setup else None
