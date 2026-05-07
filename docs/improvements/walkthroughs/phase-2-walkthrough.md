# Phase 2 Walkthrough: Zone Manager & Strategy Runner

## What was done

### 1. Created `backend/app/core/zone_manager.py` (NEW)

A thread-safe singleton cache for `ContextState` objects, keyed by `(symbol, strategy_name)`.

**API:**

| Method | Purpose |
|--------|---------|
| `update(symbol, strategy_name, state)` | Store `ContextState` after `update_context()` runs |
| `get_context(symbol, strategy_name)` | Retrieve cached `ContextState` or `None` |
| `get_active_zones(symbol, strategy_name)` | Return `list[ActiveZone]` from cached context |
| `is_price_near_zone(symbol, strategy_name, price)` | Return `True` if price is inside or within 2% of any cached zone |
| `invalidate_symbol(symbol)` | Clear all entries for a symbol (on session stop) |

**Module-level singleton:** `zone_manager = ZoneManager()` — importable everywhere.

**Thread safety:** All mutations go through `threading.Lock`, following the same pattern as `scanner.py`, `sse.py`, and `indicators.py`.

**Proximity check logic:**
- If no zones cached for the symbol/strategy → `False`
- If price is inside a zone (`zone.contains_price(price)`) → `True`
- If distance from price to nearest zone edge ≤ `price * 0.02` → `True`
- Otherwise → `False`

### 2. Added `run_mtf_scan()` to `backend/app/core/strategy_runner.py`

New static method alongside the existing `run_single_scan()` and `scan_historical()`.

**Signature:**
```python
@staticmethod
def run_mtf_scan(strategy, symbol, timeframe, ltf_candles,
                 ltf_indicators, current_price, min_confidence_override=None)
```

**Differences from `run_single_scan()`:**

| Aspect | `run_single_scan` | `run_mtf_scan` |
|--------|------------------|----------------|
| Strategy call | `strategy.scan()` | `strategy.evaluate_trigger()` |
| Entry default | `candles[-1].close` | `current_price` |
| context_tf/execution_tf | Not tagged | Tagged from strategy attrs if signal leaves them empty |
| Exception message | `Error in {name}` | `Error in MTF {name}` |

**Safety wrapping (identical to `run_single_scan`):**
- Exception handling → returns `None` instead of crashing
- Confidence filter using `min_confidence_override` or `strategy.min_confidence`
- Default SL populated via `strategy.calculate_sl()`
- Default TP populated via `strategy.calculate_tp()`

**Note:** Strategies with the default no-op `evaluate_trigger()` (returns `None`) will simply produce no signals from `run_mtf_scan()`.

## Verification

Run these tests (from project root with `PYTHONPATH=backend`):

```bash
# Round-trip test
python3 -c "
from app.core.zone_manager import zone_manager
from app.core.base_strategy import ContextState, ActiveZone

# update / get_context round-trip
state = ContextState(regime='BULLISH', active_zones=[ActiveZone('sr', 'LONG', 100.0, 98.0)])
zone_manager.update('BTCUSDT', 'TestStrat', state)
ctx = zone_manager.get_context('BTCUSDT', 'TestStrat')
assert ctx is not None and ctx.regime == 'BULLISH'
print('round-trip: OK')

# is_price_near_zone — price far from zone
assert not zone_manager.is_price_near_zone('BTCUSDT', 'TestStrat', 200.0)
print('far from zone: OK')

# is_price_near_zone — price inside zone
assert zone_manager.is_price_near_zone('BTCUSDT', 'TestStrat', 99.0)
print('inside zone: OK')

# is_price_near_zone — price within 2%
assert zone_manager.is_price_near_zone('BTCUSDT', 'TestStrat', 101.5)
print('within 2%: OK')

# is_price_near_zone — no zones cached
assert not zone_manager.is_price_near_zone('ETHUSDT', 'TestStrat', 3000.0)
print('no zones: OK')

# get_active_zones
zones = zone_manager.get_active_zones('BTCUSDT', 'TestStrat')
assert len(zones) == 1 and zones[0].zone_type == 'sr'
print('get_active_zones: OK')

# invalidate_symbol
zone_manager.invalidate_symbol('BTCUSDT')
assert zone_manager.get_context('BTCUSDT', 'TestStrat') is None
print('invalidate: OK')
"

# run_mtf_scan — default strategy returns None
python3 -c "
from app.core.base_strategy import BaseStrategy, Candle, Indicators
from app.core.strategy_runner import StrategyRunner

class NoOpStrat(BaseStrategy):
    name = 'NoOp'; timeframes = ['1h']
    def scan(self, *a, **kw): return None

strat = NoOpStrat()
candles = [Candle.from_df_row(pd.Series({'open_time':'2025-01-01','open':99,'high':101,'low':98,'close':100,'volume':1000}))]
import pandas as pd
signal = StrategyRunner.run_mtf_scan(strat, 'BTCUSDT', '1h', candles, Indicators(), 100.0)
assert signal is None
print('default evaluate_trigger returns None: OK')
"

# Existing tests
pytest backend/tests/test_strategy_runner.py -v
```

## Files changed

| Action | File |
|--------|------|
| NEW | `backend/app/core/zone_manager.py` |
| MODIFY | `backend/app/core/strategy_runner.py` — added `run_mtf_scan()` method |
