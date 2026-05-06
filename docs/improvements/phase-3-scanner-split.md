# Phase 3: Scanner Split Streams

**Goal**: Refactor `LiveScanner._on_candle_close()` into Context Stream + Execution Stream, and add ON_TOUCH evaluation to `_on_price_update()`.

**Risk**: **High** — this modifies the core live scanning loop.  
**Depends on**: Phase 1, Phase 2

## Files Changed

| Action | File | What |
|--------|------|------|
| MODIFY | `backend/app/core/scanner.py` | Split candle close handler, add touch eval to price handler |

## Step 3.1 — Extract `_handle_signal()` Helper

Before splitting streams, extract the duplicated signal handling logic from `_on_candle_close()` into a reusable method. Currently lines 391-410 handle WatchingManager, SSE, Telegram, and LLM queue.

```python
def _handle_signal(self, session_id, signal, strategy, candle_objects, indicators, sr_zones, htf_candles=None):
    """Unified signal handler — WatchingManager, SSE, Telegram, LLM queue."""
    setup_dict, is_new = WatchingManager.create_or_update_setup(session_id, signal)
    event_type = "setup_detected" if is_new else "setup_updated"
    sse_manager.publish(event_type, setup_dict)

    if is_new:
        telegram_queue.enqueue_watching_alert(setup_dict['id'])
        if hasattr(strategy, 'should_confirm_with_llm') and strategy.should_confirm_with_llm(signal):
            llm_queue.enqueue_signal(
                watching_setup_id=setup_dict['id'],
                signal=signal,
                candles=candle_objects,
                indicators=indicators,
                sr_zones=sr_zones,
                htf_candles=htf_candles,
            )
```

## Step 3.2 — Add Context Stream to `_on_candle_close()`

Inside the existing strategy loop in `_on_candle_close()`, add MTF context update logic **before** the strategy scan:

```python
for strat_name in session.strategy_names:
    strategy = registry.get_by_name(strat_name)
    if not strategy:
        continue

    # --- NEW: MTF Context Update ---
    # If this candle's timeframe matches the strategy's context_tf,
    # refresh the HTF context state and cache it in ZoneManager.
    if strategy.has_mtf_support() and timeframe == strategy.context_tf:
        htf_candles_for_ctx = self._fetch_candles_for_tf(symbol, strategy.context_tf, limit=50)
        htf_ind = self._compute_indicators_for_tf(symbol, strategy.context_tf)
        if htf_candles_for_ctx and htf_ind:
            strategy.update_context(symbol, htf_candles_for_ctx, htf_ind, sr_zones)
            zone_manager.update(symbol, strat_name, strategy.context)
            print(f"[LiveScanner]    🔄 Context updated: {strat_name} "
                  f"regime={strategy.context.regime} zones={len(strategy.context.active_zones)}")

    # --- Execution routing by mode ---
    if strategy.has_mtf_support():
        exec_tf = strategy.execution_tf
        if strategy.execution_mode == ExecutionMode.ON_CLOSE and timeframe == exec_tf:
            signal = StrategyRunner.run_mtf_scan(strategy, symbol, timeframe,
                                                  candle_objects, indicators, current_price)
            if signal:
                self._handle_signal(session_id, signal, strategy, candle_objects, indicators, sr_zones)

        elif strategy.execution_mode == ExecutionMode.HYBRID and timeframe == exec_tf:
            if zone_manager.is_price_near_zone(symbol, strat_name, current_price):
                signal = StrategyRunner.run_mtf_scan(strategy, symbol, timeframe,
                                                      candle_objects, indicators, current_price)
                if signal:
                    self._handle_signal(session_id, signal, strategy, candle_objects, indicators, sr_zones)

        # ON_TOUCH: handled in _on_price_update(), not here

    else:
        # --- LEGACY PATH (unchanged) ---
        if timeframe not in strategy.timeframes:
            continue
        signal = StrategyRunner.run_single_scan(strategy=strategy, ...)
        if signal:
            self._handle_signal(session_id, signal, strategy, candle_objects, indicators, sr_zones, htf_candles)
```

## Step 3.3 — Add Helper Methods for TF-Specific Data

Add two helper methods to `LiveScanner`:

```python
def _fetch_candles_for_tf(self, symbol, timeframe, limit=50):
    """Fetch candles from DB for a specific timeframe."""
    from app.models.db import Candle as CandleModel
    db_candles = (CandleModel.query
        .filter_by(symbol=symbol, timeframe=timeframe)
        .order_by(CandleModel.open_time.desc())
        .limit(limit).all())
    if not db_candles:
        return None
    return [Candle.from_db_row(c.to_dict()) for c in reversed(db_candles)]

def _compute_indicators_for_tf(self, symbol, timeframe):
    """Compute indicators for a specific timeframe."""
    from app.core.indicators import IndicatorService
    result = IndicatorService.compute_all(symbol, timeframe, include_series=True)
    if not result.get('latest'):
        return None
    series = result.get('series', {})
    count = result.get('candle_count', 0)
    if count > 0 and series:
        return StrategyRunner.prepare_indicators_snapshot(series, count - 1)
    return None
```

## Step 3.4 — Add ON_TOUCH Evaluation to `_on_price_update()`

Extend the existing `_on_price_update()` method:

```python
def _on_price_update(self, session_id, symbol, price, timestamp):
    # ... existing price tracking + outcome_tracker.check_price() ...
    # ... existing SSE publish ...

    # --- NEW: ON_TOUCH evaluation ---
    with self._lock:
        session = self._sessions.get(session_id)
        if not session or session.status != "active":
            return

    from app.core.strategy_loader import registry
    from app.core.base_strategy import ExecutionMode

    for strat_name in session.strategy_names:
        strategy = registry.get_by_name(strat_name)
        if not strategy or strategy.execution_mode != ExecutionMode.ON_TOUCH:
            continue
        if not zone_manager.is_price_near_zone(symbol, strat_name, price):
            continue

        # Throttle: max 1 eval per 500ms per strategy
        throttle_key = f"touch_{symbol}_{strat_name}"
        now = time.time()
        if now - self._live_candle_throttle.get(throttle_key, 0) < 0.5:
            continue
        self._live_candle_throttle[throttle_key] = now

        signal = strategy.evaluate_trigger(symbol, strategy.execution_tf, [], None, price)
        if signal:
            if self._app:
                with self._app.app_context():
                    self._handle_signal(session_id, signal, strategy, [], None, [])
```

## Step 3.5 — Clean Up Session Stop

In `stop_session()`, add zone cache invalidation:

```python
zone_manager.invalidate_symbol(session.symbol)
```

## Verification

- [ ] Start a session with a legacy strategy (no MTF) — works exactly as before
- [ ] Context update logs appear when a context_tf candle closes
- [ ] ON_CLOSE MTF strategy only fires on execution_tf candle close
- [ ] HYBRID strategy only evaluates when price is near a cached zone
- [ ] ON_TOUCH strategy fires in `_on_price_update()` path
- [ ] Throttle prevents >2 evals/second per strategy
- [ ] `stop_session()` clears zone cache
- [ ] No regressions on existing live scanning
