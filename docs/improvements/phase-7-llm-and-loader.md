# Phase 7: LLM Dual-Context & Strategy Loader

**Goal**: Update the LLM confirmation layer to accept dual-context payloads (HTF macro + LTF micro) and update the strategy loader to expose MTF metadata to the frontend.

**Risk**: Low — additive changes to prompt construction and metadata serialization.  
**Depends on**: Phase 1, Phase 6 (needs migrated strategies producing MTF signals)

## Files Changed

| Action | File | What |
|--------|------|------|
| MODIFY | `backend/app/core/llm_client.py` | Dual-context prompt template |
| MODIFY | `backend/app/core/llm_queue.py` | Pass HTF context through queue |
| MODIFY | `backend/app/core/strategy_loader.py` | Expose MTF metadata in registry |

---

## Step 7.1 — Dual-Context Prompt Template

**File**: `backend/app/core/llm_client.py`

Update the prompt builder to detect MTF signals (those with `context_tf` populated) and restructure the prompt into two explicit sections.

**Current prompt structure** (single-TF):
```
You are analyzing {symbol} on {timeframe}...
Candles: [last 10 candles]
Indicators: EMA, RSI, MACD...
Signal: {direction} at {entry}...
```

**New prompt structure** (dual-context, when `signal.context_tf` is set):
```
=== MACRO CONTEXT (HTF — {context_tf}) ===
Regime: {regime}
Active Zone: {zone_type} at {zone_top}-{zone_bottom}
HTF Indicators: EMA50={val}, EMA200={val}, RSI={val}
HTF Candles (last 5): ...
Summary: {htf_context_summary}

=== MICRO TRIGGER (LTF — {execution_tf}) ===
Trigger: {ltf_trigger_summary}
LTF Indicators: EMA9={val}, EMA21={val}, RSI={val}
LTF Candles (last 10): ...

=== TRADE PROPOSAL ===
Direction: {direction}
Entry: {entry}, SL: {sl}, TP1: {tp1}, TP2: {tp2}
Confidence: {confidence}
Strategy Notes: {notes}

Your job: Does the MICRO trigger align with the MACRO context?
Confirm, Reject, or Modify the trade with reasoning.
```

**Implementation**: Add a conditional branch in the prompt builder:

```python
def _build_prompt(self, signal, candles, indicators, sr_zones, htf_candles=None):
    if signal.context_tf and signal.htf_context_summary:
        return self._build_dual_context_prompt(signal, candles, indicators, sr_zones)
    else:
        return self._build_legacy_prompt(signal, candles, indicators, sr_zones, htf_candles)
```

The existing prompt logic moves into `_build_legacy_prompt()` unchanged. The new `_build_dual_context_prompt()` constructs the macro/micro structure above.

For legacy signals (no `context_tf`), the prompt is identical to today — zero regression risk.

---

## Step 7.2 — Pass Context Through LLM Queue

**File**: `backend/app/core/llm_queue.py`

Update `enqueue_signal()` to accept optional HTF context:

```python
def enqueue_signal(self, watching_setup_id, signal, candles, indicators,
                   sr_zones, htf_candles=None, htf_context=None):  # NEW param
    payload = {
        'watching_setup_id': watching_setup_id,
        'signal': signal,
        'candles': candles,
        'indicators': indicators,
        'sr_zones': sr_zones,
        'htf_candles': htf_candles,
        'htf_context': htf_context,  # NEW — ContextState or None
    }
    self._queue.put(payload)
```

In the queue consumer, pass `htf_context` through to `LLMClient.evaluate_signal()`.

Update `scanner.py`'s `_handle_signal()` to pass the context when available:

```python
htf_ctx = zone_manager.get_context(signal.symbol, strategy.name) if strategy.has_mtf_support() else None
llm_queue.enqueue_signal(..., htf_context=htf_ctx)
```

---

## Step 7.3 — Strategy Loader Metadata

**File**: `backend/app/core/strategy_loader.py`

Update `get_all()` to include MTF metadata in the returned dict:

```python
def get_all(self) -> list[dict]:
    result = []
    with self._lock:
        for name, instance in self._strategies.items():
            result.append({
                # ... existing fields ...
                'name': instance.name,
                'description': instance.description,
                'timeframes': instance.timeframes,
                'version': instance.version,
                'strategy_type': self._types.get(name, 'unknown'),
                'enabled': self._enabled.get(name, True),
                'min_confidence': instance.min_confidence,
                # NEW
                'execution_mode': instance.execution_mode.value,
                'context_tf': instance.context_tf or None,
                'execution_tf': instance.execution_tf or None,
                'has_mtf_support': instance.has_mtf_support(),
            })
    return result
```

Update `sync_with_db()` to persist `execution_mode` and `context_tf`:

```python
if existing:
    self._enabled[name] = existing.enabled
    instance.min_confidence = existing.min_confidence
else:
    record = Strategy(
        name=name,
        description=instance.description,
        strategy_type=self._types.get(name, 'builtin'),
        timeframes=json.dumps(instance.timeframes),
        enabled=True,
        min_confidence=instance.min_confidence,
        execution_mode=instance.execution_mode.value,  # NEW
        context_tf=instance.context_tf or None,          # NEW
    )
    db.session.add(record)
```

---

## Verification

- [ ] Legacy signal → prompt is identical to pre-phase-7 (no regression)
- [ ] MTF signal with `context_tf` set → prompt has MACRO CONTEXT + MICRO TRIGGER sections
- [ ] `htf_context_summary` and `ltf_trigger_summary` appear in the prompt
- [ ] LLM queue accepts and passes `htf_context` without errors
- [ ] `llm_prompt_logs` table stores the dual-context prompt text
- [ ] `/api/strategies` endpoint returns `execution_mode`, `context_tf`, `execution_tf` for each strategy
- [ ] DB `strategies` table has `execution_mode` and `context_tf` columns populated
- [ ] Frontend can display strategy categorization (Group A/B/C) from the metadata
