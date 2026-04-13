import json
import time
import threading
import requests
import websocket
from datetime import datetime

def fetch_klines(symbol: str, interval: str, start_time: int, end_time: int):
    """
    Fetch OHLCV data from Binance REST API and paginate automatically.
    start_time and end_time should be provided in milliseconds.
    """
    base_url = "https://fapi.binance.com/fapi/v1/klines"
    limit = 1000
    all_candles = []
    
    current_start = start_time

    while current_start < end_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_time,
            "limit": limit
        }
        
        response = requests.get(base_url, params=params)
        
        if response.status_code != 200:
            raise Exception(f"Binance API Error: {response.text}")
            
        data = response.json()
        
        if not data:
            break
            
        for row in data:
            # row[0] is open_time in ms
            # The format is described in Binance docs
            all_candles.append({
                "symbol": symbol,
                "timeframe": interval,
                "open_time": datetime.fromtimestamp(row[0] / 1000.0),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5])
            })
            
        # Update current_start to be right after the last returned candle
        last_time = data[-1][0]
        if current_start == last_time + 1:
            # We are not progressing, exit to prevent infinite loop
            break
        current_start = last_time + 1
        
        # Avoid hitting rate limits too hard
        time.sleep(0.1)

    return all_candles


class BinanceStreamManager:
    """
    Manages Binance WebSocket kline streams for live candle data.

    Architecture:
    - One combined stream URL for all symbol/timeframe pairs in a session
    - Uses websocket-client in a background daemon thread
    - Detects candle close events (kline.x == True) and fires on_candle_close callback
    - Tracks live price from unclosed candles and fires on_price_update callback
    - Supports auto-reconnect with exponential backoff
    - Thread-safe start/stop
    """

    BINANCE_WS_BASE = "wss://fstream.binance.com/stream"

    def __init__(
        self,
        symbol: str,
        timeframes: list[str],
        on_candle_close=None,
        on_price_update=None,
        max_retries: int = 20,
    ):
        """
        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            timeframes: List of timeframe strings (e.g. ["1h", "4h"])
            on_candle_close: Callback(symbol, timeframe, candle_data_dict) on closed candles
            on_price_update: Callback(symbol, price, timestamp) on every tick
            max_retries: Max reconnection attempts before giving up
        """
        self.symbol = symbol.upper()
        self.timeframes = timeframes
        self.on_candle_close = on_candle_close
        self.on_price_update = on_price_update
        self.max_retries = max_retries

        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._retry_count = 0
        self._lock = threading.Lock()

    def _build_stream_url(self) -> str:
        """Build the combined stream URL for all symbol/timeframe pairs."""
        streams = []
        sym_lower = self.symbol.lower()
        for tf in self.timeframes:
            streams.append(f"{sym_lower}@kline_{tf}")
        stream_param = "/".join(streams)
        return f"{self.BINANCE_WS_BASE}?streams={stream_param}"

    def _on_message(self, ws, message: str):
        """Handle incoming WebSocket messages."""
        try:
            msg = json.loads(message)
            data = msg.get("data", {})
            event_type = data.get("e")

            if event_type != "kline":
                return

            kline = data.get("k", {})
            symbol = data.get("s", "").upper()
            timeframe = kline.get("i", "")
            is_closed = kline.get("x", False)
            close_price = float(kline.get("c", 0))

            # Always fire price update for live ticker
            if self.on_price_update and close_price > 0:
                tick_time = datetime.fromtimestamp(data.get("E", 0) / 1000.0)
                try:
                    self.on_price_update(symbol, close_price, tick_time)
                except Exception as e:
                    print(f"[BinanceWS] Error in on_price_update: {e}")

            # Only process closed candles for strategy scanning
            if is_closed and self.on_candle_close:
                candle_data = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open_time": datetime.fromtimestamp(kline.get("t", 0) / 1000.0),
                    "open": float(kline.get("o", 0)),
                    "high": float(kline.get("h", 0)),
                    "low": float(kline.get("l", 0)),
                    "close": float(kline.get("c", 0)),
                    "volume": float(kline.get("v", 0)),
                }
                try:
                    self.on_candle_close(symbol, timeframe, candle_data)
                except Exception as e:
                    print(f"[BinanceWS] Error in on_candle_close: {e}")

        except json.JSONDecodeError:
            print(f"[BinanceWS] Failed to parse message: {message[:100]}")
        except Exception as e:
            print(f"[BinanceWS] Unexpected error in message handler: {e}")

    def _on_error(self, ws, error):
        """Handle WebSocket errors."""
        print(f"[BinanceWS] Error for {self.symbol}: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close — attempt reconnection if still running."""
        print(f"[BinanceWS] Connection closed for {self.symbol} "
              f"(status={close_status_code}, msg={close_msg})")

        if self._running and self._retry_count < self.max_retries:
            self._retry_count += 1
            # Exponential backoff: 1s, 2s, 4s, 8s, ... max 60s
            delay = min(2 ** (self._retry_count - 1), 60)
            print(f"[BinanceWS] Reconnecting in {delay}s "
                  f"(attempt {self._retry_count}/{self.max_retries})...")
            time.sleep(delay)
            if self._running:
                self._connect()
        elif self._retry_count >= self.max_retries:
            print(f"[BinanceWS] Max retries ({self.max_retries}) exceeded for {self.symbol}. Giving up.")
            self._running = False

    def _on_open(self, ws):
        """Handle successful WebSocket connection."""
        self._retry_count = 0  # Reset on successful connect
        print(f"[BinanceWS] Connected for {self.symbol} — "
              f"streaming {', '.join(self.timeframes)}")

    def _connect(self):
        """Create and run a new WebSocket connection."""
        url = self._build_stream_url()
        self._ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        # run_forever blocks — called from within the daemon thread
        self._ws.run_forever(ping_interval=30, ping_timeout=10)

    def start(self):
        """Start the WebSocket stream in a background daemon thread."""
        with self._lock:
            if self._running:
                print(f"[BinanceWS] Already running for {self.symbol}")
                return

            self._running = True
            self._retry_count = 0
            self._thread = threading.Thread(
                target=self._connect,
                name=f"binance-ws-{self.symbol.lower()}",
                daemon=True,
            )
            self._thread.start()
            print(f"[BinanceWS] Started stream thread for {self.symbol}")

    def stop(self):
        """Stop the WebSocket stream and clean up."""
        with self._lock:
            if not self._running:
                return

            self._running = False
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
            print(f"[BinanceWS] Stopped stream for {self.symbol}")

    @property
    def is_running(self) -> bool:
        """Check if the stream is currently active."""
        return self._running

