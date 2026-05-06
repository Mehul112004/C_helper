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

- [ ] Each strategy instantiates without error
- [ ] `strategy.execution_mode == ExecutionMode.ON_CLOSE` for all 5
- [ ] `strategy.has_mtf_support()` returns True for all 5
- [ ] `update_context()` correctly sets regime from HTF data
- [ ] `evaluate_trigger()` fires only when direction matches HTF regime
- [ ] Legacy `scan()` path unchanged — can still be called directly
- [ ] Backtest with legacy path produces identical results to pre-migration
