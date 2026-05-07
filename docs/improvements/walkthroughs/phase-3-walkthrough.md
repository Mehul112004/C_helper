# Phase 3 Walkthrough: Scanner Split Streams

## What was done

### 1. Extracted `_handle_signal()` helper (Step 3.1)

New unified method at `scanner.py:929` replacing duplicated signal-handling code that previously existed inline in `_on_candle_close()`. Handles:

- `WatchingManager.create_or_update_setup()`
- `sse_manager.publish()` with correct event type (`setup_detected` vs `setup_updated`)
- `telegram_queue.enqueue_watching_alert()` on new setups
- `llm_queue.enqueue_signal()` if strategy supports LLM confirmation

Used by all execution paths: legacy scan, MTF ON_CLOSE, MTF HYBRID, and ON_TOUCH.

### 2. Added MTF Context Stream + Execution Routing (Step 3.2)

Rewrote the strategy loop in `_on_candle_close()` (scanner.py lines 373-445) with MTF-aware routing:

| Path | Trigger | Method Called |
|------|---------|---------------|
| MTF ON_CLOSE | `timeframe == strategy.execution_tf` | `StrategyRunner.run_mtf_scan()` |
| MTF HYBRID | `timeframe == exec_tf` + price near zone | `StrategyRunner.run_mtf_scan()` |
| MTF ON_TOUCH | N/A (handled in `_on_price_update`) | `strategy.evaluate_trigger()` |
| LEGACY | `timeframe in strategy.timeframes` | `StrategyRunner.run_single_scan()` |

**Context update** happens when `timeframe == strategy.context_tf`:
- Fetches HTF candles via `_fetch_candles_for_tf()`
- Computes HTF indicators via `_compute_indicators_for_tf()`
- Calls `strategy.update_context()` and `zone_manager.update()`

### 3. Added Helper Methods (Step 3.3)

- **`_fetch_candles_for_tf(symbol, timeframe, limit=50)`** (line 950): Fetches candle data from DB for any timeframe, not just the HTF mapped one. Used for MTF context updates.
- **`_compute_indicators_for_tf(symbol, timeframe)`** (line 961): Computes an Indicators snapshot for any timeframe. Used for MTF context updates.

### 4. Added ON_TOUCH Evaluation (Step 3.4)

Extended `_on_price_update()` (lines 488-513) to evaluate ON_TOUCH strategies on every price tick:

- Filters to `ExecutionMode.ON_TOUCH` strategies only
- Skips if price not near a cached zone (`zone_manager.is_price_near_zone()`)
- Throttle: max 1 eval per 500ms per strategy (same throttle dict as live candles)
- Calls `strategy.evaluate_trigger(symbol, exec_tf, [], None, price)` directly
- Routes signal through `_handle_signal()` within app context

### 5. Zone Cache Invalidation on Stop (Step 3.5)

Added `zone_manager.invalidate_symbol(session.symbol)` to `stop_session()` (line 233), clearing all cached context states when a session ends.

## Files Changed

| Action | File |
|--------|------|
| MODIFY | `backend/app/core/scanner.py` — 5 sections modified |

## Verification

All tests pass (218/219, 1 pre-existing fibonacci test failure):

```bash
PYTHONPATH=backend conda run -n crypto-signals python3 -m pytest backend/tests/ -v
```

### Manual verification checks

1. **Legacy strategy unchanged** — all existing strategies (`EMA Crossover`, `RSI Reversal`, etc.) have `has_mtf_support() == False` → take legacy path identical to before.

2. **No imports crash** — `from app.core.scanner import live_scanner` loads without error; `ZoneManager`, `ExecutionMode`, `StrategyRunner` all imported correctly.

3. **`_handle_signal` dedup** — legacy and MTF paths both route through the same method, eliminating copy-paste signal handling.

4. **ON_TOUCH throttle** — `_live_candle_throttle` dict reused for `touch_*` keys, preventing >2 evaluations/second/strategy.

5. **Session stop cleanup** — `zone_manager.invalidate_symbol()` clears all entries for that symbol regardless of strategy.
