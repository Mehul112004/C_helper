# Phase 2: Zone Manager & Strategy Runner

**Goal**: Build the central zone cache and add MTF scan methods to StrategyRunner.

**Risk**: Low — new file + additive methods to existing file.  
**Depends on**: Phase 1

## Files Changed

| Action | File | What |
|--------|------|------|
| NEW | `backend/app/core/zone_manager.py` | Central zone cache singleton |
| MODIFY | `backend/app/core/strategy_runner.py` | Add `run_mtf_scan()` method |

## Step 2.1 — Create ZoneManager

**File**: `backend/app/core/zone_manager.py` (NEW)

Central in-memory cache of `ContextState` per `(symbol, strategy_name)`. Key methods:

- `update(symbol, strategy_name, state)` — store after `update_context()` runs
- `get_context(symbol, strategy_name)` — retrieve cached context
- `is_price_near_zone(symbol, strategy_name, price)` — fast proximity check (2% threshold). Returns `True` if price is inside or near any cached `ActiveZone`. Used by execution stream to skip `evaluate_trigger()` in no-man's-land.
- `invalidate_symbol(symbol)` — clear all caches on session stop
- `get_active_zones(symbol, strategy_name)` — return zone list

Thread-safe via `threading.Lock`. Module-level singleton: `zone_manager = ZoneManager()`.

## Step 2.2 — Add `run_mtf_scan()` to StrategyRunner

**File**: `backend/app/core/strategy_runner.py`

New static method alongside existing `run_single_scan()`:

```python
@staticmethod
def run_mtf_scan(strategy, symbol, timeframe, ltf_candles, ltf_indicators,
                 current_price, min_confidence_override=None):
```

- Calls `strategy.evaluate_trigger()` instead of `strategy.scan()`
- Same safety wrapping: exception handling, confidence filter, SL/TP population
- Tags `signal.context_tf` and `signal.execution_tf` from strategy attrs
- No changes to existing `run_single_scan()` or `scan_historical()`

## Verification

- [ ] `zone_manager.update()` / `get_context()` round-trips correctly
- [ ] `is_price_near_zone()` returns False when price far from zones
- [ ] `is_price_near_zone()` returns True when price within 2% of zone
- [ ] `invalidate_symbol()` clears all entries for that symbol
- [ ] `run_mtf_scan()` returns None for strategies with default `evaluate_trigger()`
- [ ] All existing tests pass unchanged
