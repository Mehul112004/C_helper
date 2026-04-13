"""
Unit tests for WatchingManager (app/core/watching.py)
Tests create/update deduplication, candle-close tick expiry, session cleanup, and queries.
"""

import os
import uuid

import pytest
from app.models.db import db, WatchingSetup
from app.core.watching import WatchingManager
from app.core.base_strategy import SetupSignal


@pytest.fixture
def app():
    """Create a test Flask app with in-memory SQLite database."""
    os.environ['SIGNAL_EXPIRY_CANDLES'] = '3'
    from app import create_app
    test_app = create_app(test_config={
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def ctx(app):
    with app.app_context():
        yield


def _make_signal(
    strategy_name="EMA Crossover", symbol="BTCUSDT", timeframe="4h",
    direction="LONG", confidence=0.72, entry=67200.0, sl=66800.0,
    tp1=67800.0, tp2=68400.0, notes="Test signal",
) -> SetupSignal:
    return SetupSignal(
        strategy_name=strategy_name, symbol=symbol, timeframe=timeframe,
        direction=direction, confidence=confidence, entry=entry,
        sl=sl, tp1=tp1, tp2=tp2, notes=notes,
    )


class TestCreateOrUpdateSetup:
    def test_create_new_setup(self, ctx):
        session_id = str(uuid.uuid4())
        setup_dict, is_new = WatchingManager.create_or_update_setup(session_id, _make_signal())
        assert is_new is True
        assert setup_dict['symbol'] == 'BTCUSDT'
        assert setup_dict['status'] == 'WATCHING'
        assert setup_dict['candles_since_detected'] == 0
        assert setup_dict['expiry_candles'] == 3

    def test_update_existing_setup_dedup(self, ctx):
        session_id = str(uuid.uuid4())
        setup1, _ = WatchingManager.create_or_update_setup(session_id, _make_signal(confidence=0.65))
        record = WatchingSetup.query.get(setup1['id'])
        record.candles_since_detected = 2
        db.session.commit()

        setup2, is_new = WatchingManager.create_or_update_setup(session_id, _make_signal(confidence=0.80, notes="Re-fire"))
        assert is_new is False
        assert setup2['id'] == setup1['id']
        assert setup2['confidence'] == 0.80
        assert setup2['candles_since_detected'] == 0

    def test_different_strategy_creates_new(self, ctx):
        sid = str(uuid.uuid4())
        _, n1 = WatchingManager.create_or_update_setup(sid, _make_signal(strategy_name="EMA Crossover"))
        _, n2 = WatchingManager.create_or_update_setup(sid, _make_signal(strategy_name="RSI Reversal"))
        assert n1 is True and n2 is True

    def test_different_timeframe_creates_new(self, ctx):
        sid = str(uuid.uuid4())
        _, n1 = WatchingManager.create_or_update_setup(sid, _make_signal(timeframe="1h"))
        _, n2 = WatchingManager.create_or_update_setup(sid, _make_signal(timeframe="4h"))
        assert n1 is True and n2 is True

    def test_different_session_creates_new(self, ctx):
        _, n1 = WatchingManager.create_or_update_setup(str(uuid.uuid4()), _make_signal())
        _, n2 = WatchingManager.create_or_update_setup(str(uuid.uuid4()), _make_signal())
        assert n1 is True and n2 is True


class TestTickCandleClose:
    def test_tick_increments_counter(self, ctx):
        sid = str(uuid.uuid4())
        setup, _ = WatchingManager.create_or_update_setup(sid, _make_signal())
        WatchingManager.tick_candle_close(sid, "BTCUSDT", "4h")
        assert WatchingSetup.query.get(setup['id']).candles_since_detected == 1

    def test_tick_expires_at_threshold(self, ctx):
        sid = str(uuid.uuid4())
        setup, _ = WatchingManager.create_or_update_setup(sid, _make_signal())
        WatchingManager.tick_candle_close(sid, "BTCUSDT", "4h")
        WatchingManager.tick_candle_close(sid, "BTCUSDT", "4h")
        expired = WatchingManager.tick_candle_close(sid, "BTCUSDT", "4h")
        assert len(expired) == 1
        assert expired[0]['status'] == 'EXPIRED'

    def test_only_affects_matching_tf(self, ctx):
        sid = str(uuid.uuid4())
        s_btc, _ = WatchingManager.create_or_update_setup(sid, _make_signal(symbol="BTCUSDT", timeframe="4h"))
        s_eth, _ = WatchingManager.create_or_update_setup(sid, _make_signal(symbol="ETHUSDT", timeframe="1h"))
        WatchingManager.tick_candle_close(sid, "BTCUSDT", "4h")
        assert WatchingSetup.query.get(s_btc['id']).candles_since_detected == 1
        assert WatchingSetup.query.get(s_eth['id']).candles_since_detected == 0

    def test_dedup_resets_expiry(self, ctx):
        sid = str(uuid.uuid4())
        setup, _ = WatchingManager.create_or_update_setup(sid, _make_signal())
        WatchingManager.tick_candle_close(sid, "BTCUSDT", "4h")
        WatchingManager.tick_candle_close(sid, "BTCUSDT", "4h")
        WatchingManager.create_or_update_setup(sid, _make_signal())
        assert WatchingSetup.query.get(setup['id']).candles_since_detected == 0


class TestExpireSetup:
    def test_expire_single(self, ctx):
        sid = str(uuid.uuid4())
        setup, _ = WatchingManager.create_or_update_setup(sid, _make_signal())
        assert WatchingManager.expire_setup(setup['id'])['status'] == 'EXPIRED'

    def test_expire_nonexistent(self, ctx):
        assert WatchingManager.expire_setup(str(uuid.uuid4())) is None

    def test_expire_all_for_session(self, ctx):
        sid = str(uuid.uuid4())
        for n in ["EMA Crossover", "RSI Reversal", "MACD Momentum"]:
            WatchingManager.create_or_update_setup(sid, _make_signal(strategy_name=n))
        assert WatchingManager.expire_all_for_session(sid) == 3
        assert len(WatchingManager.get_active_setups(sid)) == 0


class TestGetSetups:
    def test_get_active_watching_only(self, ctx):
        sid = str(uuid.uuid4())
        WatchingManager.create_or_update_setup(sid, _make_signal(strategy_name="EMA Crossover"))
        s2, _ = WatchingManager.create_or_update_setup(sid, _make_signal(strategy_name="RSI Reversal"))
        WatchingManager.expire_setup(s2['id'])
        active = WatchingManager.get_active_setups(sid)
        assert len(active) == 1

    def test_get_setup_by_id(self, ctx):
        sid = str(uuid.uuid4())
        setup, _ = WatchingManager.create_or_update_setup(sid, _make_signal())
        assert WatchingManager.get_setup(setup['id']) is not None
        assert WatchingManager.get_setup(str(uuid.uuid4())) is None
