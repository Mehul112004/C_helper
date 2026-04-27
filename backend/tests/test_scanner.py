"""
Unit tests for LiveScanner (app/core/scanner.py)
Tests session lifecycle, max-2 enforcement, and candle-close handler integration.
"""

import os
import uuid
from unittest.mock import patch, MagicMock

import pytest
from app.models.db import db
from app.core.scanner import LiveScanner, AnalysisSession, MAX_SESSIONS


@pytest.fixture
def app():
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
def scanner(app):
    s = LiveScanner(app=app)
    s._persist_session = MagicMock()
    s._backfill_historical_data = MagicMock()
    s._ensure_sr_zones = MagicMock()
    yield s
    s.stop_all()


class TestSessionLifecycle:
    @patch('app.core.scanner.BinanceStreamManager')
    def test_start_session(self, MockStream, scanner):
        MockStream.return_value.start = MagicMock()
        result = scanner.start_session("BTCUSDT", ["EMA Crossover"])
        assert result['symbol'] == 'BTCUSDT'
        assert result['status'] == 'active'
        assert 'session_id' in result
        assert len(scanner.get_active_sessions()) == 1

    @patch('app.core.scanner.BinanceStreamManager')
    def test_stop_session(self, MockStream, scanner):
        MockStream.return_value.start = MagicMock()
        MockStream.return_value.stop = MagicMock()
        session = scanner.start_session("BTCUSDT", ["EMA Crossover"])
        assert scanner.stop_session(session['session_id']) is True
        assert len(scanner.get_active_sessions()) == 0

    @patch('app.core.scanner.BinanceStreamManager')
    def test_stop_nonexistent_session(self, MockStream, scanner):
        assert scanner.stop_session(str(uuid.uuid4())) is False

    @patch('app.core.scanner.BinanceStreamManager')
    def test_stop_all(self, MockStream, scanner):
        MockStream.return_value.start = MagicMock()
        MockStream.return_value.stop = MagicMock()
        scanner.start_session("BTCUSDT", ["EMA Crossover"])
        scanner.start_session("ETHUSDT", ["RSI Reversal"])
        scanner.stop_all()
        assert len(scanner.get_active_sessions()) == 0


class TestMaxSessions:
    @patch('app.core.scanner.MAX_SESSIONS', 2)
    @patch('app.core.scanner.BinanceStreamManager')
    def test_max_sessions_enforced(self, MockStream, scanner):
        MockStream.return_value.start = MagicMock()
        scanner.start_session("BTCUSDT", ["EMA Crossover"])
        scanner.start_session("ETHUSDT", ["RSI Reversal"])
        with pytest.raises(ValueError, match="Maximum"):
            scanner.start_session("SOLUSDT", ["MACD Momentum"])

    @patch('app.core.scanner.BinanceStreamManager')
    def test_duplicate_symbol_rejected(self, MockStream, scanner):
        MockStream.return_value.start = MagicMock()
        scanner.start_session("BTCUSDT", ["EMA Crossover"])
        with pytest.raises(ValueError, match="already active"):
            scanner.start_session("BTCUSDT", ["RSI Reversal"])

    @patch('app.core.scanner.BinanceStreamManager')
    def test_invalid_strategy_rejected(self, MockStream, scanner):
        with pytest.raises(ValueError, match="Unknown strategy"):
            scanner.start_session("BTCUSDT", ["Nonexistent Strategy"])


class TestSessionMetadata:
    @patch('app.core.scanner.BinanceStreamManager')
    def test_timeframes_resolved_from_strategies(self, MockStream, scanner):
        MockStream.return_value.start = MagicMock()
        result = scanner.start_session("BTCUSDT", ["EMA Crossover"])
        # EMA Crossover has timeframes: ["15m", "1h", "4h"]
        assert "15m" in result['timeframes']
        assert "1h" in result['timeframes']
        assert "4h" in result['timeframes']

    @patch('app.core.scanner.BinanceStreamManager')
    def test_timeframes_merged_across_strategies(self, MockStream, scanner):
        MockStream.return_value.start = MagicMock()
        # EMA Crossover: 15m, 1h, 4h  |  RSI Reversal: 1h, 4h
        result = scanner.start_session("BTCUSDT", ["EMA Crossover", "RSI Reversal"])
        assert sorted(result['timeframes']) == sorted(["5m", "15m", "1h", "4h"])

    @patch('app.core.scanner.BinanceStreamManager')
    def test_live_price_initially_none(self, MockStream, scanner):
        MockStream.return_value.start = MagicMock()
        result = scanner.start_session("BTCUSDT", ["EMA Crossover"])
        assert result['live_price'] is None


class TestAnalysisSessionDataclass:
    def test_to_dict(self):
        from datetime import datetime
        session = AnalysisSession(
            session_id="abc-123",
            symbol="BTCUSDT",
            strategy_names=["EMA Crossover"],
            timeframes=["1h", "4h"],
            created_at=datetime(2026, 1, 1),
            live_price=67000.0,
        )
        d = session.to_dict()
        assert d['session_id'] == 'abc-123'
        assert d['live_price'] == 67000.0
        assert d['status'] == 'active'
