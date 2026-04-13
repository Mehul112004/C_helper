"""
Unit tests for BinanceStreamManager (app/utils/binance.py)
Tests message parsing, candle-close detection, live price extraction,
stream URL building, and lifecycle management.

Note: These tests mock the WebSocket connection — they don't connect to Binance.
"""

import json
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.utils.binance import BinanceStreamManager


class TestBinanceStreamURL:
    """Test stream URL construction."""

    def test_single_timeframe_url(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        url = mgr._build_stream_url()
        assert "btcusdt@kline_1h" in url
        assert url.startswith("wss://stream.binance.com:9443/stream?streams=")

    def test_multiple_timeframes_url(self):
        mgr = BinanceStreamManager("ETHUSDT", ["15m", "1h", "4h"])
        url = mgr._build_stream_url()
        assert "ethusdt@kline_15m" in url
        assert "ethusdt@kline_1h" in url
        assert "ethusdt@kline_4h" in url
        # Streams are separated by "/"
        assert url.count("/") >= 2

    def test_symbol_case_insensitive(self):
        mgr1 = BinanceStreamManager("btcusdt", ["1h"])
        mgr2 = BinanceStreamManager("BTCUSDT", ["1h"])
        assert mgr1._build_stream_url() == mgr2._build_stream_url()

    def test_symbol_stored_uppercase(self):
        mgr = BinanceStreamManager("ethusdt", ["1h"])
        assert mgr.symbol == "ETHUSDT"


class TestBinanceMessageParsing:
    """Test _on_message parsing of Binance kline WebSocket messages."""

    def _make_kline_message(
        self,
        symbol="BTCUSDT",
        timeframe="1h",
        is_closed=False,
        open_price=67000.0,
        high_price=67500.0,
        low_price=66800.0,
        close_price=67200.0,
        volume=1234.5,
        open_time_ms=1700000000000,
        event_time_ms=1700000060000,
    ) -> str:
        """Generate a mock Binance kline WebSocket message."""
        return json.dumps({
            "stream": f"{symbol.lower()}@kline_{timeframe}",
            "data": {
                "e": "kline",
                "E": event_time_ms,
                "s": symbol,
                "k": {
                    "t": open_time_ms,
                    "T": open_time_ms + 3600000,
                    "s": symbol,
                    "i": timeframe,
                    "o": str(open_price),
                    "c": str(close_price),
                    "h": str(high_price),
                    "l": str(low_price),
                    "v": str(volume),
                    "x": is_closed,
                },
            },
        })

    def test_unclosed_candle_fires_price_update_only(self):
        price_updates = []
        candle_closes = []

        mgr = BinanceStreamManager(
            "BTCUSDT",
            ["1h"],
            on_candle_close=lambda s, tf, d: candle_closes.append((s, tf, d)),
            on_price_update=lambda s, p, t: price_updates.append((s, p, t)),
        )

        msg = self._make_kline_message(is_closed=False, close_price=67200.0)
        mgr._on_message(None, msg)

        assert len(price_updates) == 1
        assert price_updates[0][0] == "BTCUSDT"
        assert price_updates[0][1] == 67200.0
        assert len(candle_closes) == 0

    def test_closed_candle_fires_both_callbacks(self):
        price_updates = []
        candle_closes = []

        mgr = BinanceStreamManager(
            "BTCUSDT",
            ["1h"],
            on_candle_close=lambda s, tf, d: candle_closes.append((s, tf, d)),
            on_price_update=lambda s, p, t: price_updates.append((s, p, t)),
        )

        msg = self._make_kline_message(
            is_closed=True,
            open_price=67000.0,
            high_price=67500.0,
            low_price=66800.0,
            close_price=67200.0,
            volume=1234.5,
        )
        mgr._on_message(None, msg)

        # Both callbacks should fire
        assert len(price_updates) == 1
        assert len(candle_closes) == 1

        # Verify candle data
        _, tf, candle = candle_closes[0]
        assert tf == "1h"
        assert candle["symbol"] == "BTCUSDT"
        assert candle["open"] == 67000.0
        assert candle["high"] == 67500.0
        assert candle["low"] == 66800.0
        assert candle["close"] == 67200.0
        assert candle["volume"] == 1234.5
        assert isinstance(candle["open_time"], datetime)

    def test_non_kline_event_ignored(self):
        price_updates = []

        mgr = BinanceStreamManager(
            "BTCUSDT",
            ["1h"],
            on_price_update=lambda s, p, t: price_updates.append((s, p, t)),
        )

        msg = json.dumps({
            "stream": "btcusdt@trade",
            "data": {"e": "trade", "s": "BTCUSDT", "p": "67000.00"},
        })
        mgr._on_message(None, msg)

        assert len(price_updates) == 0

    def test_invalid_json_handled_gracefully(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        mgr._on_message(None, "not valid json{{{")  # Should not raise

    def test_no_callbacks_set_is_safe(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        msg = self._make_kline_message(is_closed=True)
        mgr._on_message(None, msg)  # Should not raise

    def test_callback_exception_does_not_crash(self):
        def bad_callback(s, p, t):
            raise RuntimeError("Boom!")

        mgr = BinanceStreamManager(
            "BTCUSDT",
            ["1h"],
            on_price_update=bad_callback,
        )
        msg = self._make_kline_message(is_closed=False)
        mgr._on_message(None, msg)  # Should not raise — error is caught


class TestBinanceStreamLifecycle:
    """Test start/stop and state management."""

    def test_initial_state(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        assert not mgr.is_running
        assert mgr._retry_count == 0

    @patch.object(BinanceStreamManager, '_connect')
    def test_start_sets_running(self, mock_connect):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        mgr.start()
        assert mgr.is_running
        assert mgr._thread is not None
        # Clean up
        mgr._running = False

    def test_stop_clears_state(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        mgr._running = True
        mgr._ws = MagicMock()
        mgr.stop()
        assert not mgr.is_running
        assert mgr._ws is None

    def test_double_start_is_safe(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        mgr._running = True
        mgr.start()  # Should not create second thread

    def test_stop_when_not_running_is_safe(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        mgr.stop()  # Should not raise


class TestBinanceReconnection:
    """Test reconnection logic."""

    def test_on_close_increments_retry(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"], max_retries=3)
        mgr._running = True

        # Mock _connect to prevent actual reconnection
        with patch.object(mgr, '_connect'):
            with patch('app.utils.binance.time.sleep'):
                mgr._on_close(None, 1006, "abnormal closure")
                assert mgr._retry_count == 1

    def test_on_close_gives_up_after_max_retries(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"], max_retries=2)
        mgr._running = True
        mgr._retry_count = 2  # Already at max

        mgr._on_close(None, 1006, "abnormal closure")
        assert not mgr.is_running

    def test_on_open_resets_retry_count(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        mgr._retry_count = 5
        mgr._on_open(None)
        assert mgr._retry_count == 0

    def test_on_close_does_not_reconnect_when_stopped(self):
        mgr = BinanceStreamManager("BTCUSDT", ["1h"])
        mgr._running = False

        with patch.object(mgr, '_connect') as mock_connect:
            mgr._on_close(None, 1000, "normal closure")
            mock_connect.assert_not_called()


class TestBinanceMultiTimeframe:
    """Test handling of multiple timeframes in one stream."""

    def test_different_timeframes_in_same_stream(self):
        candle_closes = []

        mgr = BinanceStreamManager(
            "BTCUSDT",
            ["15m", "1h", "4h"],
            on_candle_close=lambda s, tf, d: candle_closes.append(tf),
        )

        # Simulate candle closes on different timeframes
        for tf in ["15m", "1h", "4h"]:
            msg = json.dumps({
                "stream": f"btcusdt@kline_{tf}",
                "data": {
                    "e": "kline",
                    "E": 1700000000000,
                    "s": "BTCUSDT",
                    "k": {
                        "t": 1700000000000,
                        "i": tf,
                        "o": "67000",
                        "c": "67200",
                        "h": "67500",
                        "l": "66800",
                        "v": "100",
                        "x": True,
                    },
                },
            })
            mgr._on_message(None, msg)

        assert candle_closes == ["15m", "1h", "4h"]
