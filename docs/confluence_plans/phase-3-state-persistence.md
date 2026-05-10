# Phase 3: State Persistence & Data Integrity — Implementation Plan

## Objective

Eliminate database bloat by adopting a Snapshot Pattern. Only write to the database when a signal fires or a threshold is breached. All market structure is computed in-memory during the scanner loop, not persisted as individual rows.

---

## 3A: The Problem — Current Persistence Model

### Current State
- `IndicatorService` computes indicators, caches them in-memory with `(symbol, timeframe, last_open_time)` key
- `SREngine.persist_zones()` writes every S/R zone to the `sr_zones` table — potential for hundreds of rows per symbol
- `LiveScanner._upsert_candle()` writes every candle to DB (this is correct and necessary — candles are the source of truth)
- Strategy signals go to `watching_setups` table (correct)
- Confirmed signals go to `confirmed_signals` table (correct)

### The Problem
If we add FVG extraction and OB extraction, persisting every zone to the database would generate:
- ~50 FVGs per 1000 candles (each lasting 5-50 candles)
- ~20 OBs per 1000 candles (each lasting 10-200 candles)
- This is 70+ new rows per symbol per timeframe, per refresh

With 10 symbols × 4 timeframes × 70 zones = 2800 DB rows per scan cycle. This is unsustainable.

### The Solution: Snapshot Pattern

Calculate everything in-memory. Only persist when something matters.

---

## 3B: The Snapshot Pattern

### Principle

> Market structure is ephemeral. Zones are born and die within a scanner cycle. The only permanent artifact is the `SetupSignal` record.

### Implementation

#### 1. What goes to the database (persistent)

| Data | Table | When |
|------|-------|------|
| OHLCV candles | `candles` | Every candle close (unchanged) |
| Strategy signals | `watching_setups` | When `signal == 1` (unchanged) |
| Confirmed signals | `confirmed_signals` | When LLM confirms (unchanged) |
| S/R zones | `sr_zones` | Periodic refresh (unchanged — S/R zones are longer-lived) |

#### 2. What stays in-memory (ephemeral)

| Data | Location | Lifetime |
|------|----------|----------|
| FVG zones | DataFrame in scanner loop | One scan cycle |
| Order Blocks | DataFrame in scanner loop | One scan cycle |
| Indicator values | IndicatorService cache | Until invalidated |
| Temporal events | DataFrame in scanner loop | One scan cycle |

#### 3. The `context_data` Column

When a `SetupSignal` is created, serialize the EXACT state of all active zones, indicators, and events at that moment into a JSON column. This serves the LLM prompt builder and the frontend without any database recalculations.

```python
# app/models/db.py — Add to WatchingSetup and ConfirmedSignal
context_data = db.Column(db.JSON, nullable=True)
# Structure:
# {
#   "active_zones": {
#     "fvg": [{"upper": 45000.0, "lower": 44800.0, "created_at": "2026-05-10T12:00:00Z"}],
#     "ob": [{"upper": 45100.0, "lower": 44900.0, "direction": "bullish", ...}],
#     "sr": [{"upper": 45200.0, "lower": 45000.0, "strength": 0.65, ...}]
#   },
#   "indicators": {
#     "rsi_14": 32.5,
#     "ema_50": 45120.0,
#     "ema_200": 44500.0,
#     "atr_14": 350.0
#   },
#   "events": {
#     "choch_bullish_recent": true,
#     "bos_bullish_recent": false
#   },
#   "confidence_breakdown": {
#     "base": 0.50,
#     "fvg_overlap": 0.20,
#     "rsi_oversold": 0.15,
#     "choch_recent": 0.10,
#     "total": 0.95
#   }
# }
```

#### 4. Serialization Utility

```python
# app/core/context_serializer.py (NEW)

def serialize_context(df: pd.DataFrame, signal_idx: int) -> dict:
    """
    Extract the state of all active zones, indicators, and events
    at the exact candle index where a signal fired.

    Args:
        df: Pre-processed DataFrame with all feature columns
        signal_idx: The integer position index where signal == 1

    Returns:
        JSON-serializable dict for context_data column
    """
    row = df.iloc[signal_idx]

    def _safe(val):
        """Convert numpy/pandas types to JSON-safe Python types."""
        if pd.isna(val):
            return None
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        if isinstance(val, (pd.Timestamp,)):
            return val.isoformat()
        if isinstance(val, (np.bool_,)):
            return bool(val)
        return val

    context = {
        'candle': {
            'open_time': str(row['open_time']),
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': float(row['volume']),
        },
        'active_zones': {},
        'indicators': {},
        'events': {},
        'confidence_breakdown': {},
    }

    # ── Active zones (only where _active is True at this row) ──
    zone_prefixes = {
        'fvg': ['fvg_upper', 'fvg_lower', 'fvg_volume', 'fvg_created_at'],
        'ob':  ['ob_upper', 'ob_lower', 'ob_volume', 'ob_direction', 'ob_created_at'],
        'sr':  ['sr_support_upper', 'sr_support_lower', 'sr_support_strength',
                'sr_resistance_upper', 'sr_resistance_lower', 'sr_resistance_strength'],
    }
    for prefix, cols in zone_prefixes.items():
        active_col = f'{prefix}_active'
        if active_col in df.columns and row.get(active_col):
            zone_entry = {}
            for col in cols:
                if col in df.columns:
                    val = _safe(row[col])
                    if val is not None:
                        zone_entry[col.replace(f'{prefix}_', '')] = val
            if zone_entry:
                context['active_zones'][prefix] = zone_entry

    # ── Indicator snapshots ──
    indicator_cols = ['rsi', 'ema_9', 'ema_21', 'ema_50', 'ema_100', 'ema_200',
                      'atr', 'macd_line', 'macd_signal', 'macd_histogram',
                      'bb_upper', 'bb_middle', 'bb_lower', 'bb_width',
                      'volume_ma']
    for col in indicator_cols:
        if col in df.columns:
            val = _safe(row[col])
            if val is not None:
                context['indicators'][col] = val

    # ── Event states ──
    event_cols = [c for c in df.columns if c.startswith('event_')]
    for col in event_cols:
        val = _safe(row.get(col))
        if val is not None:
            context['events'][col] = bool(val)

    # ── Confidence breakdown (Phase 2: conf_* columns) ──
    conf_cols = [c for c in df.columns if c.startswith('conf_')]
    total = 0.0
    for col in conf_cols:
        val = _safe(row.get(col))
        if val is not None and val > 0:
            label = col.replace('conf_', '')
            context['confidence_breakdown'][label] = val
            total += val
    context['confidence_breakdown']['total'] = total

    return context
```

---

## 3C: Database Schema Changes

### `candles` table — Add `is_closed`
```sql
ALTER TABLE candles ADD COLUMN is_closed BOOLEAN DEFAULT TRUE;
```

This enables `get_finalized_candles()` to filter out the currently-evolving candle (Trap 1 defense).

### `watching_setups` table — Add `context_data`
```sql
ALTER TABLE watching_setups ADD COLUMN context_data JSONB;
```

### `confirmed_signals` table — Add `context_data`
```sql
ALTER TABLE confirmed_signals ADD COLUMN context_data JSONB;
```

PostgreSQL JSONB is preferred over JSON for:
- Indexing capability (if needed later)
- Compression
- Faster querying within JSON fields

For SQLite fallback (test environments): Use `db.JSON` which maps to TEXT in SQLite.

---

## 3D: Scanner Loop Integration

### Updated `_on_candle_close()` Flow

The key change: `run_single_scan_v2()` must return the pre-processed DataFrame alongside the SetupSignal so `serialize_context()` can snapshot the exact row state.

```python
def _on_candle_close(self, session_id, symbol, timeframe, candle_data):
    # ── Phase 0: Data Integrity ──
    # 1. Upsert candle into DB
    self._upsert_candle(candle_data)

    # 2. Block and heal gaps (synchronous — Trap 2 defense)
    #    _detect_and_heal_gap returns False if no gap or heal failed.
    #    If a gap WAS detected but healing FAILED, abort.
    gap_result = self._detect_and_heal_gap(symbol, timeframe, candle_data['open_time'])
    # Note: _detect_and_heal_gap returns False when no gap exists (normal case).
    # We only abort if a gap was detected AND couldn't be healed.
    # The existing method logs warnings internally; we proceed regardless.

    # 3. Invalidate indicator cache
    IndicatorService.invalidate_cache(symbol, timeframe)

    # ── Phase 1: Zone Refresh (background maintenance) ──
    if timeframe in ('4h', '1d'):
        SREngine.full_refresh(symbol, timeframe)
    elif timeframe in ('1h', '15m'):
        SREngine.minor_update(symbol, timeframe)

    # ── Phase 2: Run Strategies (in-memory v2 pipeline) ──
    # Iterate through the session's registered strategy names
    for strat_name in session.strategy_names:
        strategy = registry.get_by_name(strat_name)
        if not strategy:
            continue
        if timeframe not in strategy.timeframes:
            continue

        # run_single_scan_v2 returns (SetupSignal, pre_processed_df) or (None, None)
        signal, df = StrategyRunner.run_single_scan_v2(
            strategy, symbol, timeframe,
            min_confidence_override=None,
        )

        if signal is None:
            continue

        # ── Phase 3: Serialize Context ──
        # df is the pre-processed DataFrame. The signal came from its last row.
        context = serialize_context(df, signal_idx=len(df) - 1)

        # ── Phase 4: Persist Signal ──
        # Attach context_data to the signal before passing to create_or_update_setup
        signal.context_data = context
        setup_dict, is_new = WatchingManager.create_or_update_setup(session_id, signal)

        if is_new:
            sse_manager.publish('setup_detected', setup_dict)
            telegram_queue.enqueue_watching_alert(setup_dict['id'])
            if hasattr(strategy, 'should_confirm_with_llm') and strategy.should_confirm_with_llm(signal):
                llm_queue.enqueue_signal(watching_setup_id=setup_dict['id'], signal=signal,
                                          candles=[], indicators=None, sr_zones=[],
                                          htf_candles=None)
        else:
            sse_manager.publish('setup_updated', setup_dict)

    # ── Phase 5: Expiry Tick ──
    expired = WatchingManager.tick_candle_close(session_id, symbol, timeframe)
    for exp in expired:
        sse_manager.publish('setup_expired', exp)

    # The DataFrame and all its zones are now garbage-collected.
    # Nothing persisted to DB except the signal + context_data.
```

---

## 3E: LLM Prompt Builder Integration

The `context_data` column eliminates the need for the LLM prompt builder to re-query indicators and zones from the database.

```python
# app/core/llm_client.py — Updated prompt builder

def build_prompt(setup: WatchingSetup) -> str:
    context = setup.context_data or {}
    
    # Use the snapshot directly — no DB queries needed
    zones = context.get('active_zones', {})
    indicators = context.get('indicators', {})
    events = context.get('events', {})
    breakdown = context.get('confidence_breakdown', {})
    
    prompt = f"""
    Strategy: {setup.strategy_name}
    Symbol: {setup.symbol} | Timeframe: {setup.timeframe}
    Direction: {setup.direction} | Confidence: {setup.confidence:.2f}
    
    Entry: {setup.entry} | SL: {setup.sl} | TP1: {setup.tp1} | TP2: {setup.tp2}
    
    Active Zones at Signal:
    - FVGs: {zones.get('fvg', [])}
    - Order Blocks: {zones.get('ob', [])}
    - S/R Levels: {zones.get('sr', [])}
    
    Indicators:
    - RSI(14): {indicators.get('rsi_14', 'N/A')}
    - EMA 50: {indicators.get('ema_50', 'N/A')}
    - EMA 200: {indicators.get('ema_200', 'N/A')}
    - ATR(14): {indicators.get('atr_14', 'N/A')}
    
    Confidence Breakdown:
    {breakdown}
    
    Should this trade be confirmed? Respond with VERDICT.
    """
    return prompt
```

---

## 3F: Frontend Integration

The frontend's WatchingCard component can now display zone context without additional API calls:

```javascript
// WatchingCard.tsx
const WatchingCard = ({ setup }) => {
  const context = setup.context_data || {};
  
  return (
    <div className="watching-card">
      <h3>{setup.strategy_name} — {setup.direction}</h3>
      <p>Confidence: {(setup.confidence * 100).toFixed(0)}%</p>
      
      {/* Zone visualization from context_data */}
      {context.active_zones?.fvg?.map(fvg => (
        <ZoneIndicator 
          type="fvg" 
          upper={fvg.upper} 
          lower={fvg.lower} 
        />
      ))}
      
      {/* Confidence breakdown */}
      <ConfidenceBar breakdown={context.confidence_breakdown} />
    </div>
  );
};
```

---

## 3G: Migration Path

### Step 1: Add columns (non-breaking)
```sql
ALTER TABLE candles ADD COLUMN IF NOT EXISTS is_closed BOOLEAN DEFAULT TRUE;
ALTER TABLE watching_setups ADD COLUMN IF NOT EXISTS context_data JSONB;
ALTER TABLE confirmed_signals ADD COLUMN IF NOT EXISTS context_data JSONB;
```

### Step 2: Start populating `context_data` on new signals
- Existing signals get `context_data = NULL`
- New signals get the full snapshot
- Frontend handles NULL gracefully (hide zone visualization for old signals)

### Step 3: Backfill `is_closed` for existing candles
```sql
-- Mark all past candles as closed
UPDATE candles SET is_closed = TRUE WHERE is_closed IS NULL;
```

### Step 4: Remove old zone persistence (if any new zone tables were added)
- The `sr_zones` table stays (S/R zones are longer-lived and deserve persistence)
- FVG/OB extraction results are NEVER persisted to a table

---

## 3H: Performance Considerations

### Memory Budget
For a scanner cycle with 1 symbol, 4 timeframes, 5 strategies:
- 4 DataFrames × 1000 rows × ~50 columns × 8 bytes ≈ 1.6 MB
- Each strategy runs `pre_process()` which adds columns (in-place, no copy unless needed)
- Peak memory: ~5 MB per scan cycle
- Garbage collected after each `_on_candle_close()` completion

### DB Write Budget
- Before: N zones written per scan (where N could be 50+)
- After: 0-1 signals written per scan (only when signal fires)
- Reduction: ~98% fewer writes

### JSONB Size Budget
Each `context_data` is approximately:
- Active zones: 3 FVGs + 2 OBs + 3 S/R levels ≈ 1 KB
- Indicators: 15 float values ≈ 200 bytes
- Events: 10 boolean values ≈ 150 bytes
- Confidence breakdown: 5 entries ≈ 100 bytes
- **Total**: ~1.5 KB per signal

With 100 signals per day: ~150 KB per day, ~55 MB per year. Acceptable.

---

## Trap Defenses in Phase 3

### T4: Intra-candle Invalidation
**Accepted latency**. The Watching card remains visible until the next candle close.

**The flow**:
1. A massive wick pierces an FVG at 10:32:15 (mid-candle)
2. The frontend still shows the watching card (context_data from the last close at 10:30)
3. At 10:35:00, the candle closes
4. `_on_candle_close()` runs, detects mitigation via `extract_fvgs()`, `fvg_active` → False
5. Strategy no longer fires → card not refreshed → `tick_expiry` will expire it
6. SSE `setup_expired` event removes the card from the frontend

**Why this is acceptable**: The maximum latency is one candle period (e.g., 5 minutes for 5m chart). Running extraction on live ticks would destroy performance for marginal UX gain.

---

## Phase 3 Validation Gates

1. **No Zone Table Gate**: No new database tables for FVGs, OBs, or temporal events
2. **Context Populated Gate**: Every new `watching_setup` row has non-NULL `context_data`
3. **Context Round-Trip Gate**: Serialize context → deserialize → build LLM prompt → prompt contains all expected fields
4. **Memory Leak Gate**: Run 1000 consecutive scanner cycles without memory growth (using memory_profiler)
5. **DB Write Count Gate**: Verify that a scanner cycle with 0 signals produces 0 writes (beyond the candle upsert)
6. **LLM Prompt Parity Gate**: Compare LLM prompt built from `context_data` vs. prompt built by querying DB (should be identical)
