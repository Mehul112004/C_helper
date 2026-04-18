# Support/Resistance Engine Logic

The S/R detection engine lives in `app/core/sr_engine.py` and uses structural market analysis to discover horizontal support and resistance "zones" (price bands with an upper/lower bound, rather than just single lines).

## Detection Methods

Each of these methods returns a raw list of "candidate" zones.

### `detect_swing_points(df, lookback=5)`
*   **Description:** Finds local peaks and valleys in price action.
*   **How it Works:** Iterates through the candle array. A "Swing High" requires the candle's high to be the maximum of the `±lookback` window **and** the center candle must be the *first* occurrence of that maximum (`np.argmax == lookback`). This eliminates duplicate zones when multiple candles share the same high within a window. "Swing Lows" perform the inverse check using `np.argmin`. Each detected zone also records its `_formation_idx` (the DataFrame index of the candle that formed it) so that `score_zone()` can exclude the formation candle from the touch count.
*   **Input:** Pandas DataFrame of candles, `lookback` (int).
*   **Output:** List of zone dicts (`price_level`, `zone_type`, `detection_method='swing'`, `_formation_idx`).

### `detect_round_numbers(symbol, current_price, range_pct=0.15)`
*   **Description:** Defines zones at psychological numbers (e.g., Bitcoin at $60,000 or $65,000).
*   **How it Works:** Looks up the specific asset in the `ROUND_NUMBER_CONFIG` mapping (e.g. BTC has 'small' bounds of 1000, and 'large' bounds of 5000). It establishes an upper/lower `price_range` based on the current price (±15%). Uses an integer step counter (`start + n * increment`) instead of accumulation to avoid floating-point drift — critical for assets like XRPUSDT with `increment=0.10`.
*   **Input:** `symbol` (str), `current_price` (float), `range_pct` (float).
*   **Output:** List of zone dicts marked as `round_number`.

### `detect_prev_period_hl(symbol)`
*   **Description:** Finds institutional "Previous Day" and "Previous ISO Calendar Week" levels.
*   **How it Works:** Ignores the user's targeted timeframe entirely and issues a database query exclusively for `1D` (Daily) candles (fetches up to 14). It extracts the high and low from exactly 1 element backward (Previous Day). For Previous Week, it identifies the **actual previous ISO calendar week** (Monday–Sunday) using `open_time.isocalendar()`, then takes max(high) and min(low) over those candles — replacing the old rolling 5-day approach which shifted daily.
*   **Input:** `symbol` (str).
*   **Output:** List of zone dicts marked `prev_day_hl` or `prev_week_hl`.

## Processing & Refinement Methods

### `calculate_zone_width(price_level, atr)`
*   **How it Works:** Determines how "fat" a horizontal line should be drawn. It calculates the width using ±0.25 * current ATR (Average True Range). If volatility is high, the support zone is wide; if volatility is low, the support zone is tight.

### `merge_zones(zones, atr)`
*   **Description:** Deduplicates zones that are clustered tightly together.
*   **How it Works:** Uses a **multi-pass** approach (up to 10 iterations, usually converges in 2–3). Each pass sorts by price and collapses adjacent zones within `0.5 * ATR` into averaged positions. The iteration continues until the output count stabilises, catching cascading overlaps that a single pass would miss. When merging, keeps the higher `touch_count` and more recent `timestamp`. If `resistance` and `support` merge, the zone type transforms to `both`.
*   **Input:** Overlapping zone dicts, current ATR.
*   **Output:** Consolidated, unique zone dicts.

### `score_zone(zone, df, timeframe, formation_idx=None)`
*   **Description:** Assigns mathematical significance to a verified zone.
*   **How it Works:** Scans the historical dataframe to count "touches" (how many past candles had wicks that pierced inside the bounds of this zone). If `formation_idx` is provided, that candle is excluded from the touch count to prevent the zone's formation candle from inflating the score. The formula `strength = (touches * 0.15) + timeframe_weight` is used. Maximum score is 1.0.
*   **Timeframe weights** (defined in `TIMEFRAME_WEIGHTS`): `1w: 0.50`, `1D: 0.40`, `12h: 0.35`, `8h: 0.32`, `6h: 0.30`, `4h: 0.28`, `2h: 0.22`, `1h: 0.20`, `30m: 0.15`, `15m: 0.10`, `5m: 0.07`, `3m: 0.05`, `1m: 0.03`.

## Workflow Orchestrators

### `detect_zones(symbol, timeframe, swing_lookback)`
*   **Description:** The master function that sequences the entire pipeline.
*   **How it Works:**
    1. Fetches data and asks `IndicatorService` to compute the current ATR.
    2. Runs all 3 detection methods and pools the resulting candidate dicts.
    3. Establishes initial zone boundaries around candidates using ATR.
    4. Passes the pool into `merge_zones()` to eliminate crowding.
    5. Re-calculates bounds on the merged entities.
    6. Calls `score_zone()` on finalists.
*   **Output:** Final list of polished zone dictionaries ready for database entry.

### `persist_zones(symbol, timeframe, zones)`
*   **How it Works:** Attempts PostgreSQL `insert...on_conflict_do_update` first. If the PG dialect is unavailable (e.g. SQLite in test environments), falls back to standard SQLAlchemy ORM (`query.filter_by().first()` / `db.session.add()`). A shared `_build_zone_record()` helper normalizes zone dicts for both paths.

### Thread Safety: Per-Symbol Refresh Locks
*   `SREngine` maintains a `_refresh_locks` dictionary of `threading.Lock` objects, one per symbol.
*   `full_refresh()` and `minor_update()` acquire the lock before detecting and persisting zones.
*   `LiveScanner._on_candle_close()` acquires the same lock before reading zones from the DB.
*   This prevents the scheduler from committing mid-cycle while the scanner is reading stale zone data.

### Configuration
*   `SUPPORTED_SYMBOLS` lives in `app/core/config.py` (not in `sr_engine.py`) alongside `CANDLE_WARMUP`.

---

## Background Scheduler (`app/core/scheduler.py`)

The S/R engine utilizes `apscheduler` inside the Flask context to automate zone tracking securely in the background without needing a secondary worker container. All jobs filter to **active sessions only** — symbols with no running session are skipped.

### Jobs

| Job | Trigger | Minute | Timeframes | Grace |
|-----|---------|--------|------------|-------|
| `full_zone_refresh_4h` | cron `0,4,8,12,16,20` | `:01` | `4h` | 120s |
| `full_zone_refresh_1d` | cron `0` (daily) | `:02` | `1D` | 180s |
| `minor_zone_update` | cron (hourly) | `:03` | `1h`, `15m` | 60s |
| `startup_full_refresh` | date (once on boot) | — | `4h`, `1D` | — |

*   All jobs have `coalesce=True` and `max_instances=1` to prevent thundering herd on missed runs.
*   Minute offsets are staggered to avoid concurrent DB commits.
*   The `minor_update` path in `SREngine` also calls `IndicatorService.invalidate_cache()` after persisting.

### Event-Driven Refresh (Primary for Live Sessions)

For active sessions, zone refresh is **primarily driven by candle closes** in `LiveScanner._on_candle_close()`:
*   `4h` / `1D` candle close → `SREngine.full_refresh()`
*   `1h` / `15m` candle close → `SREngine.minor_update()`

The scheduler serves as a background top-up (e.g. daily close at 00:02 UTC) rather than the primary zone maintenance mechanism.
