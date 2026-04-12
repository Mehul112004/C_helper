# API Endpoints & Control Logic

These functions exist within Flask blueprints and serve as the HTTP interface between the React frontend and the backend Python core. 

## Data Blueprint (`app/blueprints/data.py`)

### `import_binance()`
*   **Route:** `POST /api/data/import/binance`
*   **Description:** Triggers a historical data pull from Binance into the local database.
*   **How it Works:** Extracts JSON payload details, converts ISO strings to Unix timestamps, and calls `fetch_klines()`. It then performs a bulk PostgreSQL "upsert" (`ON CONFLICT DO UPDATE`) using SQLAlchemy's insert statement to gracefully handle appending to or updating existing data without unique constraint crashes.
*   **Input:** JSON body `{symbol, timeframe, start_time, end_time}`.
*   **Output:** JSON success message with the row `count` inserted.

### `import_csv()`
*   **Route:** `POST /api/data/import/csv`
*   **Description:** Processes a CSV file upload for historical candle data.
*   **How it Works:** Extracts the uploaded file part via `request.files`, reads form fields for metadata, and passes the stream to `parse_binance_csv()`. Like `import_binance()`, it bulk-upserts the resulting rows into the TimescaleDB `candles` hypertable.
*   **Input:** `multipart/form-data` with `file`, `symbol`, and `timeframe`.
*   **Output:** JSON success message with inserted row `count`.

### `get_datasets()`
*   **Route:** `GET /api/data/datasets`
*   **Description:** Retrieves a summary of all local data available for backtesting.
*   **How it Works:** Executes an aggregate SQL query using `GROUP BY symbol, timeframe` to retrieve the minimum/maximum `open_time` and total row `count` for each distinct active dataset within the `candles` table.
*   **Input:** None.
*   **Output:** JSON array containing `{symbol, timeframe, start_time, end_time, count, source}`.

## Indicators Blueprint (`app/blueprints/indicators_bp.py`)

### `get_indicators()`
*   **Route:** `GET /api/indicators`
*   **Description:** Fetches all technical indicator values for a given asset and timeframe.
*   **How it Works:** Validates expected timeframes, then invokes `IndicatorService.compute_all()`. By default, it returns only the `latest` values for lightweight API payloads, but if `include_series=true` is passed, it returns the entire historical array to accommodate charting.
*   **Input:** Query params `symbol` (str), `timeframe` (str), `include_series` (boolean, optional).
*   **Output:** Complex JSON structure with a `latest` object, an optional `series` object, and a `warnings` array if data is insufficient.

### `invalidate_cache()`
*   **Route:** `POST /api/indicators/invalidate`
*   **Description:** Manually purges the in-memory indicator cache.
*   **How it Works:** Reads optional filters from the body and forwards them to `IndicatorService.invalidate_cache()`. Allows forced recalculation when importing fresh historical data overlaps with previously cached time regions.
*   **Input:** Optional JSON body `{symbol, timeframe}`.
*   **Output:** JSON confirmation message.

## S/R Zones Blueprint (`app/blueprints/sr_zones_bp.py`)

### `get_sr_zones()`
*   **Route:** `GET /api/sr-zones`
*   **Description:** Retrieves a list of scored S/R zones from the database.
*   **How it Works:** Queries the `sr_zones` table, dynamically applying requested filters using SQLAlchemy `.filter()`. Results are always sorted backwards by `strength_score` to prioritize the most structurally significant levels. It also checks the `updated_at` timestamps to inform the frontend of data freshness.
*   **Input:** Query params `symbol` (required), `timeframe` (optional), `min_strength` (optional), `near_price` (optional, filters to ±3%).
*   **Output:** JSON containing an array of zone objects and global `last_refreshed` metadata.

### `refresh_zones()`
*   **Route:** `POST /api/sr-zones/refresh`
*   **Description:** Manually forces the detection and persistence pipeline for S/R zones.
*   **How it Works:** Allows specifying a single symbol/timeframe or 'all'. It calls `SREngine.detect_zones()` to generate zones, then `SREngine.persist_zones()` to save them to PostgreSQL, bypassing the normal 4h/1h scheduler.
*   **Input:** JSON body `{symbol}` (required) and `{timeframe}` (optional).
*   **Output:** JSON success message tracking how many zones were detected and saved.
