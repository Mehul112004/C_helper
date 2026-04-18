# Codebase Knowledge Base

Strictly derived from files shared in this session. Nothing inferred beyond what the code explicitly contains.

---

## Files Shared

| File | Class/Module |
|------|--------------|
| `app/core/indicators.py` | `IndicatorService` |
| `app/core/live_scanner.py` | `LiveScanner`, `AnalysisSession` |
| `app/core/base_strategy.py` | `Candle`, `Indicators`, `SetupSignal`, `BaseStrategy` |
| `app/core/strategy_runner.py` | `StrategyRunner` |
| `app/core/strategy_loader.py` | `StrategyRegistry` |
| `app/core/sr_engine.py` | `SREngine` |
| `app/core/scheduler.py` | `init_scheduler`, `full_zone_refresh`, `minor_zone_update` |
| `app/models/db.py` | `Strategy` model (inline paste only) |
| `app/core/config.py` | `CANDLE_WARMUP = 400`, `SUPPORTED_SYMBOLS` (fix-added) |

---

## Data Flow (from `live_scanner.py`)

On each candle close, `LiveScanner._on_candle_close` runs this sequence:

```
1. _upsert_candle(candle_data)
2. IndicatorService.invalidate_cache(symbol, timeframe)
3. IndicatorService.compute_all(symbol, timeframe, include_series=True)
4. SRZone.query — fetch zones within ±3% of current price
         └─ acquire SREngine.get_refresh_lock(symbol) before query (FIX-SCH-3)
5. CandleModel.query — last 50 candles → list[Candle]
6. Trigger S/R zone refresh based on candle timeframe (FIX-SR-1):
         if timeframe in ('4h', '1D'): SREngine.full_refresh(symbol, timeframe)
         elif timeframe in ('1h', '15m'): SREngine.minor_update(symbol, timeframe)
7. StrategyRunner.run_single_scan() × each strategy in session
       └─ signal → WatchingManager.create_or_update_setup()
                 → sse_manager.publish(setup_detected / setup_updated)
                 → telegram_queue.enqueue_watching_alert()
                 → llm_queue.enqueue_signal()  (if strategy.should_confirm_with_llm)
8. WatchingManager.tick_candle_close() → sse_manager.publish(setup_expired)
9. sse_manager.publish(candle_close)
```

On each price tick, `_on_price_update` updates `session.live_price` and publishes `price_update`.

---

## `AnalysisSession` (dataclass)

Fields: `session_id`, `symbol`, `strategy_names`, `timeframes`, `created_at`, `status`, `stream_manager`, `live_price`, `live_price_updated_at`

Status values: `"active"` | `"stopping"` | `"stopped"`

---

## `LiveScanner`

**Constraints:** Max 10 concurrent sessions. One session per symbol.

**`start_session` flow:**
1. Strategy + timeframe resolution (outside lock)
2. `with self._lock` → check max sessions, check duplicate symbol (status `"active"` OR `"stopping"`) → create session + stream → add to `_sessions`
3. Release lock → `_persist_session()`, `_backfill_historical_data()`, `_ensure_sr_zones()`
4. `stream.start()`

**`stop_session` flow:**
1. `with self._lock` → set status `"stopping"`
2. Release lock → `stream_manager.stop()`
3. `WatchingManager.expire_all_for_session()`
4. `_update_session_status("stopped")`
5. `with self._lock` → set status `"stopped"`

**`_backfill_historical_data`:**
- Skips timeframes that already have `≥ CANDLE_WARMUP` candles in DB
- Fetches via `fetch_klines(symbol, tf, start_ms, now_ms)`
- Lookback = `CANDLE_WARMUP × tf_minutes × 1.2` to account for gaps
- Calls `_upsert_candle(commit=False)` per candle, single `db.session.commit()` after loop

**`_ensure_sr_zones`:**
- Per-timeframe check: calls `SREngine.full_refresh(symbol, tf)` only for timeframes with no existing `SRZone` records

**`_upsert_candle(commit=True)`:**
- Tries PostgreSQL `ON CONFLICT DO UPDATE` on `(symbol, timeframe, open_time)`
- Falls back to manual merge (SQLite/testing)
- `commit` parameter controls whether to commit immediately (False during backfill)

**`_fetch_htf_candles` — HTF map:**
```
1m→5m, 3m→15m, 5m→15m, 15m→1h, 30m→4h,
1h→4h, 2h→4h, 4h→1d, 6h→1d, 8h→1d, 12h→1d, 1d→1w
```
Returns `Optional[list[Candle]]` — last 10 candles of the HTF.

**`get_active_sessions`:** Returns list of `AnalysisSession` where `status == "active"`. Used by scheduler to filter active symbols (FIX-SCH-1).

**Thread safety:** `self._lock` (threading.Lock) guards all `_sessions` mutations. Both `_on_candle_close` and `_on_price_update` snapshot session under lock before proceeding.

**SSE events published:** `session_started`, `session_stopped`, `candle_close`, `price_update`, `setup_detected`, `setup_updated`, `setup_expired`

---

## `IndicatorService`

**Indicators:** EMA (9, 21, 50, 100, 200), RSI (14), MACD (12/26/9), Bollinger Bands (20/2), ATR (14), Volume MA (20)

**Cache:** `_cache: dict` keyed by `(symbol, timeframe, last_open_time_iso)`. Protected by `_cache_lock = threading.Lock()`. Stores full result including series. Returns `series=None` if `include_series=False`.

**`compute_all` returns:**
```python
{
  'symbol', 'timeframe',
  'latest': dict,          # most recent value per indicator, NaN → None
  'series': dict,          # list of {time, value} per indicator (if include_series=True)
  'candle_count': int,
  'last_updated': str,     # ISO timestamp of last candle
  'warnings': list[str],
}
```

**Key implementation details:**
- Fetches `MIN_CANDLES_IDEAL = CANDLE_WARMUP` (400) candles, sorted ascending
- ATR: `tr.ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()` (Wilder's RMA)
- RSI: Wilder's smoothing (`ewm(alpha=1/period)`); `np.errstate(divide='ignore', invalid='ignore')` suppresses 0/0; `.where(avg_loss != 0, other=100.0)` handles pure uptrend
- `invalidate_cache`: uses `cls._cache.pop(k, None)` inside lock

---

## `Candle` (frozen dataclass) — `base_strategy.py`

Fields: `open_time: datetime`, `open`, `high`, `low`, `close`, `volume: float`

Constructors: `from_db_row(dict)`, `from_df_row(pd.Series)`

Computed properties: `body_size`, `range_size`, `upper_wick`, `lower_wick`, `is_bullish`, `is_bearish`

---

## `Indicators` (dataclass) — `base_strategy.py`

**Current bar fields:** `ema_9`, `ema_21`, `ema_50`, `ema_100`, `ema_200`, `rsi_14`, `macd_line`, `macd_signal`, `macd_histogram`, `bb_upper`, `bb_middle`, `bb_lower`, `bb_width`, `atr_14`, `volume_ma_20`

**Previous bar fields:** `prev_ema_9`, `prev_ema_21`, `prev_macd_line`, `prev_macd_signal`, `prev_macd_histogram`, `prev_rsi_14`, `prev_bb_upper`, `prev_bb_lower`, `prev_bb_width`

**History fields:** `bb_width_history` (last 20 non-None values up to idx), `rsi_14_history` (last 5 non-None values up to idx)

All fields default to `None`. Built via `Indicators.from_series(series_dict, idx)`.

**`from_series`** uses `_safe_get(series_list, position)` — returns `None` for out-of-bounds, missing, or NaN values.

---

## `SetupSignal` (dataclass) — `base_strategy.py`

Fields: `strategy_name`, `symbol`, `timeframe`, `direction` (`"LONG"` or `"SHORT"`), `confidence` (0.0–1.0), `entry`, `sl`, `tp1`, `tp2` (all `Optional[float]`), `notes: str`, `timestamp: datetime`

`__post_init__` raises `ValueError` for invalid direction or confidence out of range.

`to_dict()` returns JSON-safe dict; timestamp serialized as ISO string.

---

## `BaseStrategy` (ABC) — `base_strategy.py`

**Must implement:** `scan(symbol, timeframe, candles, indicators, sr_zones) → Optional[SetupSignal]`

**Class attributes:** `name`, `description`, `timeframes: list = []` (subclasses must declare their own list), `version`, `min_confidence = 0.5`

**Default `calculate_sl`:** recent 3-candle pivot ± 0.5 ATR buffer

**Default `calculate_tp`:** uses `signal.sl if signal.sl is not None else self.calculate_sl(...)` for risk; tp1 = 1.5R, tp2 = 3.0R; risk floor = `atr * 0.2`

**`should_confirm_with_llm`:** returns `True` by default

---

## `StrategyRunner` — `strategy_runner.py`

**`run_single_scan`:**
1. Calls `strategy.scan()` inside try/except (bad strategy → returns None)
2. Confidence filter: `min_confidence_override` or `strategy.min_confidence`
3. Sets `entry = candles[-1].close` if None
4. Sets `sl` via `strategy.calculate_sl()` if None and `atr > 0`
5. Sets `tp1`/`tp2` via `strategy.calculate_tp()` if None and `atr > 0`
6. `atr = indicators.atr_14 if indicators.atr_14 is not None else 0.0`

**`scan_historical`:**
- Skips first 50 bars (`start_idx = 50`)
- Sliding window of 50 candles per bar
- Overrides `signal.timestamp` to `candle_objects[idx].open_time`

**`prepare_indicators_snapshot`:** thin wrapper — `return Indicators.from_series(series_dict, idx)`

---

## `StrategyRegistry` — `strategy_loader.py`

Module-level singleton: `registry = StrategyRegistry()`

Internal state: `_strategies: dict[str, BaseStrategy]`, `_types: dict[str, str]`, `_enabled: dict[str, bool]`, `_lock: threading.RLock`

**`load_builtin_strategies`:** scans `app/strategies/*.py`, finds non-abstract `BaseStrategy` subclasses, instantiates and registers them. Defaults all to enabled.

**`sync_with_db`:** bulk-fetches all `Strategy` records in one query (`{s.name: s for s in Strategy.query.all()}`), loads `enabled` + `min_confidence` from DB for existing, creates new records for new strategies.

**APIs:** `get_all()`, `get_enabled()`, `get_by_name(name) → Optional[BaseStrategy]`, `is_enabled(name)`, `set_enabled(name, bool)`, `set_min_confidence(name, float)` — all protected by `self._lock`.

---

## `Strategy` DB Model — `app/models/db.py`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | autoincrement |
| `name` | String(100) | unique |
| `description` | Text | |
| `strategy_type` | String(20) | `'builtin'` or `'custom'` |
| `timeframes` | Text | JSON array e.g. `'["1h","4h"]'` |
| `enabled` | Boolean | default True |
| `min_confidence` | Float | default 0.5 |
| `code` | Text | Python source, custom strategies only |
| `created_at` / `updated_at` | DateTime(timezone=True) | server default |

`to_dict()`: parses `timeframes` JSON, exposes `has_code: bool`.

---

## `SREngine` — `app/core/sr_engine.py`

**Purpose:** Detects and manages S/R zones using three methods: swing high/low, psychological round numbers, previous day/week H/L.

**Constants:**

```python
TIMEFRAME_WEIGHTS = {
    '1w': 0.50, '1D': 0.40, '12h': 0.35, '8h': 0.32,
    '6h': 0.30, '4h': 0.28, '2h': 0.22, '1h': 0.20,
    '30m': 0.15, '15m': 0.10, '5m': 0.07, '3m': 0.05, '1m': 0.03,
}  # Fixed: previously missing entries for 1w/12h/8h/6h/2h/30m/3m/1m (FIX-SR-5)

ROUND_NUMBER_CONFIG = {
    'BTCUSDT': {'small': 1000, 'large': 5000},
    'ETHUSDT': {'small': 100, 'large': 500},
    'SOLUSDT': {'small': 10, 'large': 50},
    'XRPUSDT': {'small': 0.10, 'large': 0.50},
}
DEFAULT_ROUND_CONFIG = {'small': 100, 'large': 500}
# SUPPORTED_SYMBOLS moved to app/core/config.py (FIX-SCH-8)
```

**Threading:** Per-symbol refresh locks via `SREngine.get_refresh_lock(symbol)` — `threading.Lock` per symbol, guarded by a meta-lock. Used by both `full_refresh` and `_on_candle_close` before reading/writing `SRZone` table (FIX-SCH-3).

**Detection methods:**

`detect_swing_points(df, lookback=5)`:
- Detects swing highs (highest high in ±lookback window) and swing lows
- Uses `np.argmax(window) == lookback` to prevent duplicate zones when multiple candles share the same high (FIX-SR-8)
- Attaches `_formation_idx` to each zone dict for use by `score_zone` (FIX-SR-4)

`detect_round_numbers(symbol, current_price, range_pct=0.15)`:
- Generates zones at psychologically significant levels within ±15% of price
- Uses integer step counter `n` to avoid float accumulation: `level = round(start + n * increment, 10)` (FIX-SR-7)
- Deduplicates by rounding to 8dp

`detect_prev_period_hl(symbol)`:
- Always queries `1D` candles regardless of analysis timeframe
- Previous day: `candles_1d[1]`
- Previous week: filtered by ISO calendar week number, not rolling 5-day window (FIX-SR-2)
- Fetches up to 14 candles to ensure coverage of a full prior week

**Zone processing:**

`calculate_zone_width(price_level, atr)` → `(zone_upper, zone_lower)`:
- Zone width = `price_level ± (0.25 × ATR)`

`merge_zones(zones, atr)`:
- Merge threshold = `0.5 × ATR`
- Iterates until stable (up to 10 passes) to handle cascading overlaps (FIX-SR-6)
- On merge: averages price levels, sets `zone_type = 'both'` if types differ, keeps more recent timestamp, keeps higher `touch_count`

`score_zone(zone, df, timeframe, formation_idx=None)`:
- `strength = min(1.0, touch_count × 0.15 + tf_weight)`
- Excludes formation candle from touch count via `formation_idx` (FIX-SR-4)
- Returns zone with `strength_score`, `touch_count`, `last_tested`

`detect_zones(symbol, timeframe, swing_lookback=5)` — full pipeline:
1. Fetch up to 500 candles from DB
2. Run all three detection methods
3. Calculate zone widths (ATR-based)
4. Merge nearby zones (multi-pass)
5. Recalculate widths after merge
6. Score zones (with formation index exclusion)
7. Attach `symbol` and `timeframe` metadata

`persist_zones(symbol, timeframe, zones)`:
- PostgreSQL: `ON CONFLICT DO UPDATE` on `uq_sr_zone` constraint
- SQLite fallback: manual merge (query + update or insert) (FIX-SR-3)
- Helper `_build_zone_record(zone)` centralises field extraction and rounding

`full_refresh(symbol, timeframe)`:
- Acquires `get_refresh_lock(symbol)` before running (FIX-SCH-3)
- Calls `detect_zones` → `persist_zones`
- Calls `IndicatorService.invalidate_cache(symbol, timeframe)` after persist (FIX-SCH-4)

`minor_update(symbol, timeframe)`:
- Swing-only detection on last 50 candles
- Calls `persist_zones` for new swing zones
- Calls `IndicatorService.invalidate_cache(symbol, timeframe)` after persist (FIX-SCH-4)

---

## `Scheduler` — `app/core/scheduler.py`

**Library:** APScheduler `BackgroundScheduler(daemon=True)`

**Jobs (post-fix):**

| Job ID | Trigger | Timeframes | Offset |
|--------|---------|------------|--------|
| `startup_full_refresh` | `date` (once on boot) | 4h + 1D | immediate |
| `full_zone_refresh_4h` | cron `hour=0,4,8,12,16,20` | 4h only | `:01` |
| `full_zone_refresh_1d` | cron `hour=0` | 1D only | `:02` |
| `minor_zone_update` | cron every hour | 1h + 15m | `:03` |

All jobs: `coalesce=True`, `max_instances=1` (FIX-SCH-10)

**`full_zone_refresh(app, scanner)`:**
- Filters to `scanner.get_active_sessions()` symbols only — skips symbols with no active session (FIX-SCH-1)
- Calls `SREngine.full_refresh` + `IndicatorService.invalidate_cache` per symbol/timeframe

**`minor_zone_update(app, scanner)`:**
- Filters to active session symbols (FIX-SCH-1)
- Calls `SREngine.minor_update` per symbol/timeframe
- Cache invalidation now handled inside `SREngine.minor_update` (FIX-SCH-4)

**`init_scheduler(app, scanner)`:**
- Accepts `scanner` reference for active-session filtering
- Registers startup one-shot job before cron jobs (FIX-SCH-7)
- Shuts down cleanly via `atexit.register(lambda: scheduler.shutdown(wait=False))`

**`misfire_grace_time` values:**
- 4h job: 120s
- 1D job: 180s
- Minor update: 60s

**`SUPPORTED_SYMBOLS`:** Moved to `app/core/config.py` and imported from there in both `sr_engine.py` and `scheduler.py` (FIX-SCH-8).

---

## `app/core/config.py`

```python
CANDLE_WARMUP = 400
SUPPORTED_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']
```

---

## Fixed Bugs (do not reintroduce)

### `indicator_service.py`
- ATR: `ewm(alpha=1/period)` not `rolling().mean()`
- RSI: `np.errstate` + `.where(avg_loss != 0, other=100.0)`
- Cache: `threading.Lock` on all reads/writes; `.pop(k, None)` in invalidation
- Fetch limit: `CANDLE_WARMUP` (400), not hardcoded 250

### `live_scanner.py`
- `_on_candle_close` and `_on_price_update` snapshot session under `self._lock`
- Duplicate-symbol guard: `status in ("active", "stopping")`
- Backfill: `commit=False` per candle + single commit after loop
- `_ensure_sr_zones`: per-timeframe check, not symbol-level short-circuit
- `_fetch_htf_candles`: return type `Optional[list[Candle]]`
- Strategy resolution outside `self._lock` in `start_session`
- All imports at top of `_on_candle_close`, not inside loop
- Zone refresh now wired into `_on_candle_close` per timeframe (FIX-SR-1)
- `SREngine.get_refresh_lock(symbol)` acquired before `SRZone.query` (FIX-SCH-3)

### `base_strategy.py`
- `calculate_tp`: uses `signal.sl if signal.sl is not None` instead of recomputing
- `entry` and `atr`: explicit `is not None` checks, not `or` falsy

### `strategy_loader.py`
- `sync_with_db`: bulk-fetch in one query (no N+1)
- Registry: `threading.RLock`
- `get_by_name`: `Optional[BaseStrategy]` not `BaseStrategy | None`

### `strategy_runner.py`
- Redundant direction check removed (`SetupSignal.__post_init__` handles it)
- `start_idx = 50` not `max(50, 0)`
- `atr`: explicit `is not None` check

### `sr_engine.py`
- Zones never refreshed after init: wired into `_on_candle_close` (FIX-SR-1)
- Previous week H/L: ISO calendar week, not rolling 5-day window (FIX-SR-2)
- `persist_zones`: SQLite fallback added, `_build_zone_record` helper extracted (FIX-SR-3)
- `score_zone`: formation candle excluded from touch count via `_formation_idx` (FIX-SR-4)
- `TIMEFRAME_WEIGHTS`: all HTF map timeframes now covered (FIX-SR-5)
- `merge_zones`: multi-pass until stable, no-op dead code removed (FIX-SR-6)
- `detect_round_numbers`: integer step counter replaces accumulated addition (FIX-SR-7)
- `detect_swing_points`: `np.argmax == lookback` replaces exact float equality (FIX-SR-8)
- `full_refresh` and `minor_update`: both acquire per-symbol lock, both invalidate cache (FIX-SR-1, FIX-SCH-3, FIX-SCH-4)
- `SUPPORTED_SYMBOLS` moved to `config.py` (FIX-SCH-8)

### `scheduler.py`
- Scheduler now filters to active session symbols only (FIX-SCH-1)
- `1D` refresh separated into its own job at 00:02 UTC only (FIX-SCH-2)
- Per-symbol lock in `SREngine` prevents race with `_on_candle_close` (FIX-SCH-3)
- Minor update cache invalidation moved into `SREngine.minor_update` (FIX-SCH-4)
- Jobs staggered at :01, :02, :03 to prevent concurrent 00:01 collision (FIX-SCH-5)
- `misfire_grace_time` tightened per job cadence (FIX-SCH-6)
- Startup one-shot refresh job added (FIX-SCH-7)
- `coalesce=True` + `max_instances=1` on all jobs (FIX-SCH-10)

---

## Open / Pending Issues

### `live_scanner.py`
- `session.live_price` and `session.live_price_updated_at` written after lock release in `_on_price_update` — technically a race, low impact.

### `base_strategy.py` / `strategy_loader.py`
- `timeframes: list = []` is a shared mutable class attribute — no runtime enforcement that subclasses override it.
- Direction validation in both `SetupSignal.__post_init__` and `run_single_scan` — runner check is dead code, pending removal.

### `sr_engine.py`
- Zone widths use current ATR for all zones regardless of when they were formed. Older zones get the same band width as fresh ones — low impact in practice but not strictly correct.
- `detect_prev_period_hl` output is timeframe-independent: same PDH/PDL levels appear in every timeframe's zone set. Intentional but not documented in code.