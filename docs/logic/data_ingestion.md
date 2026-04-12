# Data Ingestion Logic

These functions handle acquiring raw OHLCV candle data from external sources and parsing it into a standardized format for the database.

## `fetch_klines(symbol, interval, start_time, end_time)`
*   **Location:** `app/utils/binance.py`
*   **Description:** Fetches historical candlestick data from Binance's REST API.
*   **How it Works:** It makes an HTTP GET request to the Binance `/api/v3/klines` endpoint. Because Binance limits responses to 1000 candles per request, this function uses a `while` loop to automatically paginate through the requested date range, updating the `startTime` parameter on each iteration. It sleeps briefly between requests to prevent rate limit violations.
*   **Input:** 
    *   `symbol` (str): e.g., 'BTCUSDT'
    *   `interval` (str): e.g., '4h'
    *   `start_time` (int): milliseconds Unix timestamp
    *   `end_time` (int): milliseconds Unix timestamp
*   **Output:** List of dictionaries containing correctly typed OHLCV values and a Python `datetime` object for `open_time`.

## `parse_binance_csv(file_stream, symbol, timeframe)`
*   **Location:** `app/utils/csv_parser.py`
*   **Description:** Parses an uploaded CSV file containing raw Binance OHLCV data.
*   **How it Works:** Uses the `pandas` library to load the CSV file into a DataFrame. It strips and lowercases column headers to robustly find required fields (`open_time`, `open`, `high`, `low`, `close`, `volume`). It handles `open_time` dynamically, parsing it correctly whether it's expressed as Unix milliseconds or as a string date (like '2023-01-01 00:00:00'). Data rows with `NaN` in required fields are dropped.
*   **Input:** 
    *   `file_stream` (file-like object): The uploaded CSV file stream.
    *   `symbol` (str): The trading pair the CSV represents.
    *   `timeframe` (str): The timeframe the CSV represents.
*   **Output:** List of dictionaries identical in structure to the output of `fetch_klines()`. Raises a `ValueError` if the CSV is structurally invalid.
