# Support/Resistance Engine Logic

The S/R detection engine lives in `app/core/sr_engine.py` and uses structural market analysis to discover horizontal support and resistance "zones" (price bands with an upper/lower bound, rather than just single lines).

## Detection Methods

Each of these methods returns a raw list of "candidate" zones.

### `detect_swing_points(df, lookback=5)`
*   **Description:** Finds local peaks and valleys in price action.
*   **How it Works:** Iterates through the candle array. A "Swing High" requires the candle's high to be greater than or equal to the high of all `N` candles prior *and* all `N` candles following (where `N` is the `lookback`). "Swing Lows" perform the inverse check on candle lows. It is highly reactive and forms the bulk of a typical chart's zones.
*   **Input:** Pandas DataFrame of candles, `lookback` (int).
*   **Output:** List of zone dicts (`price_level`, `zone_type`, `detection_method='swing'`).

### `detect_round_numbers(symbol, current_price, range_pct=0.15)`
*   **Description:** Defines zones at psychological numbers (e.g., Bitcoin at $60,000 or $65,000).
*   **How it Works:** Looks up the specific asset in the `ROUND_NUMBER_CONFIG` mapping (e.g. BTC has 'small' bounds of 1000, and 'large' bounds of 5000). It establishes an upper/lower `price_range` based on the current price (±15%). It mathematically walks through the range using floor division step algorithms to generate price levels cleanly matching the psychological integers, skipping any out-of-bounds noise.
*   **Input:** `symbol` (str), `current_price` (float), `range_pct` (float).
*   **Output:** List of zone dicts marked as `round_number`.

### `detect_prev_period_hl(symbol)`
*   **Description:** Finds institutional "Previous Day" and "Previous Week" levels.
*   **How it Works:** Ignores the user's targeted timeframe entirely and issues a database query exclusively for `1D` (Daily) candles. It extracts the high and low from exactly 1 element backward (Previous Day), and takes the max(high) and min(low) over elements index 1 through 5 (Previous Week).
*   **Input:** `symbol` (str).
*   **Output:** List of zone dicts marked `prev_day_hl` or `prev_week_hl`.

## Processing & Refinement Methods

### `calculate_zone_width(price_level, atr)`
*   **How it Works:** Determines how "fat" a horizontal line should be drawn. It calculates the width using ±0.25 * current ATR (Average True Range). If volatility is high, the support zone is wide; if volatility is low, the support zone is tight.

### `merge_zones(zones, atr)`
*   **Description:** Deduplicates zones that are clustered tightly together.
*   **How it Works:** Sorts all raw candidate zones by price, rolling through them from bottom to top. If a zone is within `0.5 * ATR` of the previous zone, they are collapsed into a single entity holding the average price of both. If `resistance` and `support` merge, the zone type transforms to `both`.
*   **Input:** Overlapping zone dicts, current ATR.
*   **Output:** Consolidated, unique zone dicts.

### `score_zone(zone, df, timeframe)`
*   **Description:** Assigns mathematical significance to a verified zone.
*   **How it Works:** Scans the historical dataframe to count "touches" (how many past candles had wicks that pierced inside the bounds of this zone). The formula `strength = (touches * 0.15) + timeframe_weight` is used. A zone discovered on the `1D` chart inherently receives a massive baseline weight bonus (+0.40) compared to a zone found on the `5m` chart (+0.05). Maximum score is 1.0.

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
*   **How it Works:** Uses SQLAlchemy Postgres Dialect `insert...on_conflict_do_update` to bulk-dump the detected zones to the `sr_zones` table. This acts as a true UPSERT, creating new zones or overwriting the bounds/scores of existing ones flawlessly.

---

## Background Scheduler (`app/core/scheduler.py`)

The S/R engine utilizes `apscheduler` inside the Flask context to automate zone tracking securely in the background without needing a secondary worker container.

*   **`full_zone_refresh`**: Scheduled to run every 4 hours exactly 1 minute past the clock (e.g. 04:01). It triggers `detect_zones()` on all symbols running the `'4h'` and `'1D'` timeframes, purging and re-evaluating the entire spectrum of detection tools (round numbers, previous H/L, swings).
*   **`minor_zone_update`**: Scheduled to run every hour at *:01*. It explicitly bypasses full recalculation. Instead, it queries only a tiny window of the most recent candles (limit: 50) and calls *only* `detect_swing_points()`. This ensures that as new localized peaks/valleys form in real-time between the 4-hour massive refreshes, the app still captures and adds them to the db.
