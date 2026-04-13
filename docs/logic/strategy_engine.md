# Strategy Engine Logic

All strategy engine components live in `app/core/` and `app/strategies/`. The engine provides a pluggable framework where any number of strategies can be registered, enabled/disabled, and executed against candle data to produce `SetupSignal` objects.

## Core Data Classes (`app/core/base_strategy.py`)

### `Candle` (frozen dataclass)
*   **Description:** Immutable representation of a single OHLCV bar.
*   **Key Properties:**
    -   `body_size` → `|close - open|`
    -   `range_size` → `high - low`
    -   `upper_wick` → `high - max(open, close)`
    -   `lower_wick` → `min(open, close) - low`
    -   `is_bullish` / `is_bearish` → direction helpers
*   **Factory Methods:** `from_db_row(dict)` and `from_df_row(pd.Series)` for conversion from database or DataFrame rows.

### `Indicators` (dataclass)
*   **Description:** Snapshot of all technical indicator values at a specific candle bar. Includes both current-bar and previous-bar values.
*   **Current Bar Fields:** `ema_9`, `ema_21`, `ema_50`, `ema_200`, `rsi_14`, `macd_line`, `macd_signal`, `macd_histogram`, `bb_upper`, `bb_middle`, `bb_lower`, `bb_width`, `atr_14`, `volume_ma_20`
*   **Previous Bar Fields:** `prev_ema_9`, `prev_ema_21`, `prev_macd_line`, `prev_macd_signal`, `prev_macd_histogram`, `prev_rsi_14`, `prev_bb_upper`, `prev_bb_lower`, `prev_bb_width`
*   **Special Field:** `bb_width_history: list[float]` — last 20 Bollinger band width values, used by the Bollinger Squeeze strategy to detect low-volatility periods without strategies needing to compute indicators themselves.
*   **Factory Method:** `from_series(series_dict, idx)` — builds a snapshot from the full indicator series output of `IndicatorService.compute_all()` at a specific candle index.

### `SetupSignal` (dataclass)
*   **Description:** The universal output of every strategy's `scan()` method. This object flows through watching cards → LLM confirmation → Telegram notification.
*   **Required Fields:** `strategy_name`, `symbol`, `timeframe`, `direction` ("LONG"/"SHORT"), `confidence` (0.0–1.0)
*   **Optional Fields:** `entry`, `sl`, `tp1`, `tp2`, `notes` (context for LLM), `timestamp`
*   **Validation:** `__post_init__` enforces valid direction and confidence bounds. Invalid values raise `ValueError`.

## BaseStrategy Contract (`app/core/base_strategy.py`)

### Abstract Class: `BaseStrategy`
*   **Required Override:** `scan(symbol, timeframe, candles, indicators, sr_zones) → SetupSignal | None`
*   **Optional Overrides:**
    -   `calculate_sl(signal, candles, atr) → float` — Default: 1.5 × ATR from entry
    -   `calculate_tp(signal, candles, atr) → (float, float)` — Default: TP1 = 2 × ATR, TP2 = 3.5 × ATR
    -   `should_confirm_with_llm(signal) → bool` — Default: `True`
*   **Class Attributes:** `name`, `description`, `timeframes`, `version`, `min_confidence` (default 0.5, configurable per strategy and per session)

## Strategy Registry (`app/core/strategy_loader.py`)

### `StrategyRegistry` (singleton)
*   **Discovery:** On startup, `load_builtin_strategies()` uses `importlib` to scan `app/strategies/` for Python files, importing each and collecting `BaseStrategy` subclasses.
*   **DB Sync:** `sync_with_db()` reconciles the in-memory registry with the `strategies` database table — creating rows for newly discovered strategies and loading `enabled` state and `min_confidence` from existing rows.
*   **Key Methods:**
    -   `get_all()` → list of strategy metadata dicts
    -   `get_enabled()` → list of enabled `BaseStrategy` instances
    -   `get_by_name(name)` → single strategy instance or None
    -   `set_enabled(name, bool)` → toggle on/off, persists to DB
    -   `set_min_confidence(name, float)` → update threshold, persists to DB

## Strategy Runner (`app/core/strategy_runner.py`)

### `StrategyRunner`
*   **`run_single_scan()`:** Wraps `strategy.scan()` with exception catching, signal validation, default SL/TP population, and minimum confidence filtering. Supports per-session `min_confidence_override`.
*   **`scan_historical()`:** Walks a historical candle DataFrame bar-by-bar (from index 50 onward), building candle windows and indicator snapshots for each bar, then running all applicable strategies. Used by tests and the backtester (Phase 7).
*   **`prepare_indicators_snapshot()`:** Delegates to `Indicators.from_series()` to build a snapshot at a specific candle index.

## Built-in Strategies (`app/strategies/`)

All 6 strategies follow the same `BaseStrategy` contract and are auto-discovered by the registry.

### EMA Crossover (`ema_crossover.py`)
*   **Mode:** Reactive | **Timeframes:** 15m, 1h, 4h
*   **Logic:** EMA 9 crosses EMA 21. Trend-filtered by EMA 50 (LONG requires close > EMA50, SHORT requires close < EMA50).
*   **Confidence:** Base 0.60 + volume (0.10) + EMA 200 alignment (0.10) + RSI mid-range (0.05)
*   **SL Override:** Tighter 1.2 × ATR (reactive crosses are faster).

### RSI Reversal (`rsi_reversal.py`)
*   **Mode:** Reactive | **Timeframes:** 1h, 4h
*   **Logic:** RSI crosses back from extreme territory (LONG: prev < 30 → curr ≥ 30, SHORT: prev > 70 → curr ≤ 70). Requires price above EMA 50 or EMA 200 for longs (below for shorts).
*   **Confidence:** Base 0.55 + MACD confirmation (0.15) + volume (0.10) + near S/R zone (0.10)

### Bollinger Band Squeeze (`bollinger_squeeze.py`)
*   **Mode:** Reactive | **Timeframes:** 1h, 4h
*   **Logic:** Detects squeeze state (previous bar's `bb_width` below the average of last 20 `bb_width` values), then fires on breakout (close beyond upper/lower band) with volume ≥ 1.2× volume_ma.
*   **Confidence:** Base 0.55 + extreme volume (0.15) + EMA alignment (0.10) + width expansion (0.10)

### MACD Momentum (`macd_momentum.py`)
*   **Mode:** Reactive | **Timeframes:** 1h, 4h, 1D
*   **Logic:** MACD line crosses signal line with histogram confirmation (positive for longs, negative for shorts). Rewards momentum buildup (histogram was opposite ≥1 bar before cross).
*   **Confidence:** Base 0.55 + momentum buildup (0.10) + EMA 50 alignment (0.15) + volume (0.10) + strong histogram delta (0.05)

### S/R Zone Rejection (`sr_rejection.py`)
*   **Mode:** Conditional | **Timeframes:** 4h, 1D
*   **Logic:** Price wick penetrates an S/R zone (strength ≥ 0.3) but closes on the opposite side, forming a rejection candle (pin bar / hammer / shooting star with dominant wick ≥ 60% of total range).
*   **Confidence:** Base 0.60 + zone strength × 0.20 + volume (0.10) + RSI alignment (0.05)

### S/R Zone Breakout (`sr_breakout.py`)
*   **Mode:** Conditional | **Timeframes:** 1h, 4h
*   **Logic:** Close breaks through an S/R zone (strength ≥ 0.25) with a strong-bodied candle (body ≥ 50% of range) and volume ≥ 1.3× volume_ma. Verifies the previous candle was on the opposite side (actual breakout, not continuation).
*   **Confidence:** Base 0.55 + strong volume (0.15) + EMA alignment (0.10) + retest pattern (0.10)

## Default SL/TP Formulas

| Direction | Stop-Loss | Take-Profit 1 | Take-Profit 2 |
|---|---|---|---|
| LONG | entry - 1.5 × ATR | entry + 2.0 × ATR | entry + 3.5 × ATR |
| SHORT | entry + 1.5 × ATR | entry - 2.0 × ATR | entry - 3.5 × ATR |

Individual strategies may override these with tighter or wider values.

## API Endpoints (`app/blueprints/strategies_bp.py`)

| Endpoint | Method | Description |
|---|---|---|
| `/api/strategies` | GET | List all strategies with metadata |
| `/api/strategies/<name>` | GET | Get single strategy details |
| `/api/strategies/<name>/toggle` | POST | Enable or disable a strategy |
| `/api/strategies/<name>/confidence` | POST | Update min_confidence threshold |
