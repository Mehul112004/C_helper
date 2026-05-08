# Phase 5: Strategy Migration — Group A (ON_CLOSE)

**Goal**: Migrate the 5 mathematical/lagging strategies to the MTF system. These keep `ON_CLOSE` mode — they only fire on LTF candle close, but now use HTF context for trend filtering.

**Risk**: Medium — each strategy is independently migrated and testable.  
**Depends on**: Phase 1, 2, 3

## Files Changed

| Action | File | Mode | context_tf | execution_tf |
|--------|------|------|-----------|-------------|
| MODIFY | `ema_crossover.py` | ON_CLOSE | 4h | 15m |
| MODIFY | `macd_momentum.py` | ON_CLOSE | 1h | 15m |
| MODIFY | `rsi_reversal.py` | ON_CLOSE | 4h | 15m |
| MODIFY | `bollinger_squeeze.py` | ON_CLOSE | 1h | 15m |
| MODIFY | `volume_climax.py` | ON_CLOSE | 1h | 1h |

## Migration Pattern (same for all Group A)

Each strategy gets 3 additions. Existing `scan()` stays unchanged for backward compat.

### 1. Set class attributes

```python
class EMACrossoverStrategy(BaseStrategy):
    execution_mode = ExecutionMode.ON_CLOSE
    context_tf = "4h"
    execution_tf = "15m"
```

### 2. Implement `update_context()`

Compute HTF regime + cache any relevant indicator values:

```python
def update_context(self, symbol, htf_candles, htf_indicators, sr_zones):
    ctx = self._context_state
    ctx.clear()

    # Determine regime from HTF EMAs
    if htf_indicators.ema_50 and htf_indicators.ema_200:
        if htf_indicators.ema_50 > htf_indicators.ema_200:
            ctx.regime = "BULLISH"
        else:
            ctx.regime = "BEARISH"

    ctx.indicators_snapshot = {
        'ema_50': htf_indicators.ema_50,
        'ema_200': htf_indicators.ema_200,
        'rsi_14': htf_indicators.rsi_14,
    }
    ctx.last_updated = datetime.utcnow()
```

### 3. Implement `evaluate_trigger()`

Check LTF crossover/signal, gated by HTF regime:

```python
def evaluate_trigger(self, symbol, timeframe, ltf_candles, ltf_indicators, current_price):
    ctx = self._context_state
    if not ctx.last_updated:
        return None  # no context yet

    # Run existing scan logic on LTF data
    signal = self.scan(symbol, timeframe, ltf_candles, ltf_indicators, [], None)
    if signal is None:
        return None

    # Gate: direction must align with HTF regime
    if ctx.regime == "BULLISH" and signal.direction == "SHORT":
        return None
    if ctx.regime == "BEARISH" and signal.direction == "LONG":
        return None

    # Enrich signal with MTF metadata
    signal.htf_context_summary = f"HTF regime: {ctx.regime} (EMA50>{'>'}EMA200)"
    signal.ltf_trigger_summary = f"EMA 9/21 crossover on {timeframe}"
    return signal
```

## Per-Strategy Details

### EMA Crossover
- **context_tf=4h**: Compute EMA50/200 regime
- **evaluate_trigger**: EMA 9/21 crossover on 15m, gated by 4H regime

### MACD Momentum
- **context_tf=1h**: Store MACD histogram phase (positive/negative)
- **evaluate_trigger**: MACD line cross on 15m, aligned with 1H histogram direction

### RSI Reversal
- **context_tf=4h**: Check if 4H RSI is at structural extreme (<35 or >65)
- **evaluate_trigger**: 15m RSI crosses back above 30 / below 70

### Bollinger Squeeze
- **context_tf=1h**: Detect squeeze state on 1H (BB inside KC)
- **evaluate_trigger**: 15m BB band break, only fire if 1H was in squeeze

### Volume Climax
- **context_tf=1h, execution_tf=1h**: Same timeframe (volume climax is inherently HTF)
- **update_context**: Evaluate trend extension state
- **evaluate_trigger**: Delegates to `scan()` since both TFs match

## Migration Order

Migrate one at a time. After each, verify:
1. Legacy `scan()` still produces identical results
2. `has_mtf_support()` returns True
3. Live scanner correctly routes through `evaluate_trigger()`
4. Signal includes `context_tf` and `execution_tf` metadata

## Verification

- [x] Each strategy instantiates without error
- [x] `strategy.execution_mode == ExecutionMode.ON_CLOSE` for all 5
- [x] `strategy.has_mtf_support()` returns True for all 5
- [x] `update_context()` correctly sets regime from HTF data
- [x] `evaluate_trigger()` fires only when direction matches HTF regime
- [x] Legacy `scan()` path unchanged — can still be called directly
- [x] Backtest with legacy path produces identical results to pre-migration

---

## Walkthrough of Changes

### Migration Pattern (all 5 strategies)

Each strategy received the same 3 structural additions. The existing `scan()` method and helper methods (`calculate_sl`, `calculate_tp`, etc.) were left untouched.

### 1. Class Attributes (MTF Configuration)

Each strategy now declares three new class-level attributes that plug it into the MTF system:

```python
execution_mode = ExecutionMode.ON_CLOSE  # Only fire on LTF candle close
context_tf = "4h"                        # HTF used for trend/regime context
execution_tf = "15m"                     # LTF used for trigger detection
```

| Strategy | `context_tf` | `execution_tf` |
|----------|-------------|---------------|
| EMA Crossover | `4h` | `15m` |
| MACD Momentum | `1h` | `15m` |
| RSI Reversal | `4h` | `15m` |
| Bollinger Squeeze | `1h` | `15m` |
| Volume Climax | `1h` | `1h` |

Volume Climax uses `1h` for both since volume climax is inherently an HTF pattern — the evaluation delegates through to the same `scan()` logic since both TFs match.

### 2. `update_context()` — HTF Regime Detection

Called by the engine at each HTF candle boundary (via `Phase 4` mechanics). Each strategy computes its own HTF regime:

- **EMA Crossover**: Compares EMA50 vs EMA200 on 4H → sets `BULLISH` or `BEARISH`
- **MACD Momentum**: Checks MACD histogram on 1H → positive = `BULLISH`, negative = `BEARISH`
- **RSI Reversal**: Checks RSI on 4H → <35 = `OVERSOLD`, >65 = `OVERBOUGHT`, else `NEUTRAL`
- **Bollinger Squeeze**: Uses `_is_squeeze()` on 1H BB/KC → `SQUEEZE` or `NO_SQUEEZE`
- **Volume Climax**: Compares EMA50 vs EMA200 on 1H → `BULLISH` or `BEARISH`

Results are cached in `self._context_state`: `regime`, `indicators_snapshot`, `last_updated`.

### 3. `evaluate_trigger()` — Gated Trigger Execution

Called by the engine on each LTF bar close (or at HTF boundaries for context updates). Pattern:

1. Check `ctx.last_updated` — return `None` if no context has been loaded yet
2. Call `self.scan()` on the LTF data (delegates to the existing scan logic)
3. Gate by HTF regime — reject signals whose direction conflicts with the HTF trend
4. Enrich the signal with MTF metadata (`htf_context_summary`, `ltf_trigger_summary`)

**Gating logic per strategy:**

- **EMA Crossover**: `BULLISH` regime rejects SHORT signals; `BEARISH` rejects LONG
- **MACD Momentum**: Same direction alignment gating based on histogram phase
- **RSI Reversal**: `OVERSOLD` rejects SHORT; `OVERBOUGHT` rejects LONG; `NEUTRAL` allows both
- **Bollinger Squeeze**: Only `SQUEEZE` regime allows signals through; `NO_SQUEEZE` gates all
- **Volume Climax**: No directional gate (both TFs match), delegates entirely to `scan()`

### Files Modified

| File | Changes |
|------|---------|
| `ema_crossover.py` | Added `ExecutionMode`/`datetime` imports, 3 class attrs, `update_context()`, `evaluate_trigger()`. Version bumped to `1.5`. |
| `macd_momentum.py` | Added `ExecutionMode`/`datetime` imports, 3 class attrs, `update_context()`, `evaluate_trigger()`. Version bumped to `1.2`. |
| `rsi_reversal.py` | Added `ExecutionMode`/`datetime` imports, 3 class attrs, `update_context()`, `evaluate_trigger()`. Version bumped to `1.2`. |
| `bollinger_squeeze.py` | Added `ExecutionMode`/`datetime` imports, 3 class attrs, `update_context()`, `evaluate_trigger()`. Version bumped to `2.3`. |
| `volume_climax.py` | Added `ExecutionMode`/`datetime` imports, 3 class attrs, `update_context()`, `evaluate_trigger()`. Version bumped to `1.2`.
