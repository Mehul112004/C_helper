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
| `app/models/db.py` | `Strategy` model (inline paste only) |
| `app/core/config.py` | `CANDLE_WARMUP = 400` (created as fix, referenced by updated files) |

---

## Data Flow (from `live_scanner.py`)

On each candle close, `LiveScanner._on_candle_close` runs this sequence:

```
1. _upsert_candle(candle_data)
2. IndicatorService.invalidate_cache(symbol, timeframe)
3. IndicatorService.compute_all(symbol, timeframe, include_series=True)
4. SRZone.query — fetch zones within ±3% of current price
5. CandleModel.query — last 50 candles → list[Candle]
6. StrategyRunner.run_single_scan() × each strategy in session
       └─ signal → WatchingManager.create_or_update_setup()
                 → sse_manager.publish(setup_detected / setup_updated)
                 → telegram_queue.enqueue_watching_alert()
                 → llm_queue.enqueue_signal()  (if strategy.should_confirm_with_llm)
7. WatchingManager.tick_candle_close() → sse_manager.publish(setup_expired)
8. sse_manager.publish(candle_close)
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

---

## Open / Pending Issues

### `live_scanner.py`
- `session.live_price` and `session.live_price_updated_at` written after lock release in `_on_price_update` — technically a race, low impact.

### `base_strategy.py` / `strategy_loader.py`
- `timeframes: list = []` is a shared mutable class attribute — no runtime enforcement that subclasses override it.
- Direction validation in both `SetupSignal.__post_init__` and `run_single_scan` — runner check is dead code, pending removal.