# Confluence Engine Restructuring — Changes Walkthrough & Verification Guide

## Overview

This walkthrough documents every file changed and every new file created across all 5 phases of the confluence engine restructuring. It also provides a step-by-step verification procedure to confirm the changes work end-to-end.

---

## Part 1: Complete File Change Manifest

### New Files Created (5)

| File | Phase | Purpose |
|------|-------|---------|
| `app/core/data_utils.py` | 1 | `get_finalized_candles()` — time-agnostic closed-candle fetcher with staleness guard. `StaleDataError` exception. |
| `app/core/indicator_service.py` | 1 | Caching wrapper around pure indicator functions. Houses the old `IndicatorService` class with cache + DB fetch + API serialization. |
| `app/core/market_structure.py` | 1 | Spatial state module — `extract_fvgs()` and `extract_order_blocks()` with masked ffill + mitigation kill-switch + lookahead bias shift(+1). |
| `app/core/events.py` | 1 | Temporal state module — `detect_choch()` (with opposing event cancellation), `detect_volume_climax()`, `detect_liquidity_sweep()`. |
| `app/core/context_serializer.py` | 3 | `serialize_context(df, signal_idx)` — snapshots zones, indicators, events, confidence breakdown into JSON for `context_data` column. |

### Existing Files Modified (12)

| File | Phase | Key Changes |
|------|-------|-------------|
| `app/core/indicators.py` | 1 | **Purified.** All cache/DB logic removed. Now pure stateless functions with NaN policy contracts: `compute_ema()`, `compute_rsi()`, `compute_macd()`, `compute_bollinger()`, `compute_atr()`, `compute_keltner()`, `compute_volume_ma()`. |
| `app/core/fractals.py` | 1 | Added DataFrame-based API: `detect_swing_points_df()`, `build_swing_list()`, `determine_trend_from_swings()`. Existing Candle-object API preserved. |
| `app/core/sr_engine.py` | 1 | Added `detect_zones_df(df, symbol, timeframe)` — DataFrame-mode S/R detection with temporally-safe `df.loc[form_idx:]` assignment (no lookahead leak). Exports `sr_active`, `sr_support_upper/lower/strength`, `sr_resistance_upper/lower/strength`. S/R zones do NOT use mitigation kill-switch. |
| `app/core/base_strategy.py` | 2, 3, 4 | **Phase 2**: Added `required_features`, `feature_config`, `get_required_lookback()`, `get_min_candles()`, `pre_process(df, symbol, timeframe)`, `generate_signals(df)` default. `scan()` made non-abstract. **Phase 3**: Added `context_data` field to `SetupSignal`. **Phase 4**: Added `safe_lt()`, `safe_gt()`, `safe_between()`, `safe_notna()` NaN guard utilities. |
| `app/core/strategy_runner.py` | 2, 3 | Added `run_single_scan_v2()` → returns `(SetupSignal, df)` tuple. Added `scan_historical_v2()` for backtester. Added `_df_row_to_candles()` / `_df_slice_to_candles()` converters. Fixed `.iloc` label-vs-position bug in `scan_historical_v2`. |
| `app/core/scanner.py` | 1 | Updated imports: `IndicatorService` now from `indicator_service`. |
| `app/core/scheduler.py` | 1 | Updated imports: `IndicatorService` now from `indicator_service`. |
| `app/core/backtest_engine.py` | 1 | Updated to use pure `compute_*` functions instead of `IndicatorService.compute_*` for vectorized indicator computation. |
| `app/models/db.py` | 3 | Added `is_closed` (Boolean) to `Candle` model. Added `context_data` (JSON) to `WatchingSetup` and `ConfirmedSignal` models. Updated `to_dict()` methods. |
| `app/core/watching.py` | 3 | `create_or_update_setup` now persists `signal.context_data` when available. |
| `app/blueprints/indicators_bp.py` | 1 | Import updated from `indicators` → `indicator_service`. |
| `scripts/queue_watching_setups.py` | 1 | Import updated from `indicators` → `indicator_service`. |
| `scripts/audit_extraction_code.py` | 4 | **NEW** — Lint script detecting `iterrows`, `itertuples`, scalar assignments, bare ffill patterns. |

### New Test Files Created (5)

| File | Tests | What It Validates |
|------|-------|-------------------|
| `tests/test_data_factory.py` | 8 helpers | Known-price DataFrame generators for deterministic extractor testing |
| `tests/test_extract_fvgs.py` | 12 | FVG detection, mitigation wick/body, lookahead bias, ffill leak, contract columns, edge cases |
| `tests/test_extract_order_blocks.py` | 5 | OB detection, contract columns, mitigation, small data resilience |
| `tests/test_extract_events.py` | 11 | ChoCh/BOS detection, opposing event cancellation, volume climax, liquidity sweep, fractal detection |
| `tests/test_invalidation_scenarios.py` | 7 | Flat market, crashes, extreme volatility, NaN resilience, double mitigation |

### Existing Test Files Modified (1)

| File | Change |
|------|--------|
| `tests/test_base_strategy.py` | Updated `test_cannot_instantiate_directly` → `test_can_instantiate_directly` (BaseStrategy no longer abstract). Updated `test_subclass_must_implement_scan` → `test_subclass_without_scan_raises_on_call` (scan() now default, raises NotImplementedError). |
| `tests/test_indicators.py` | Import updated from `indicators` → `indicator_service`. |

---

## Part 2: Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        STRATEGY LAYER                               │
│  app/strategies/*.py  (13 files, NOT yet rewritten — Phase 2 TODO) │
│  Current: uses scan() with Candle + Indicators dataclasses          │
│  Target: uses generate_signals(df) with weighted scoring matrix     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  BaseStrategy   │  app/core/base_strategy.py
                    │  pre_process()  │  Orchestrator: loads features
                    │  generate_signals()
                    │  safe_lt/gt/between()
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
┌────────▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐
│ CONTINUOUS STATE │  │ SPATIAL STATE  │  │ TEMPORAL STATE │
│ indicators.py   │  │ market_structure│  │ events.py      │
│ compute_ema()   │  │ extract_fvgs()  │  │ detect_choch() │
│ compute_rsi()   │  │ extract_obs()   │  │ detect_vol_    │
│ compute_macd()  │  │                 │  │   climax()     │
│ compute_atr()   │  │ sr_engine.py    │  │ detect_sweep() │
│ compute_bb()    │  │ detect_zones_df()│  │                │
└────────┬────────┘  └───────┬────────┘  └───────┬────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                    ┌────────▼────────┐
                    │  DATA LAYER     │
                    │  data_utils.py  │  get_finalized_candles()
                    │  models/db.py   │  Candle, WatchingSetup, etc.
                    └─────────────────┘
```

---

## Part 3: Key Logic Flows

### Flow 1: Live Signal Detection (v2 Pipeline)

```
Binance WS candle close
        │
        ▼
LiveScanner._on_candle_close()
        │
        ├─ _upsert_candle()           → candles table
        ├─ _detect_and_heal_gap()     → REST API backfill if needed
        ├─ IndicatorService.invalidate_cache()
        ├─ SREngine.full_refresh() or minor_update()
        │
        ▼
for strategy in session.strategies:
    │
    ▼
StrategyRunner.run_single_scan_v2(strategy, symbol, timeframe)
    │
    ├─ get_finalized_candles(symbol, tf, limit=lookback)
    │     → Filters out unclosed candles (Trap 1 defense)
    │     → Raises StaleDataError if candles too old (Trap 8 defense)
    │
    ├─ strategy.pre_process(df, symbol, timeframe)
    │     → Checks required_features declaration
    │     → Loads only needed: compute_rsi(), extract_fvgs(), detect_choch(), etc.
    │     → Returns enriched DataFrame
    │
    ├─ strategy.generate_signals(df)
    │     → Base requirements (hard gate)
    │     → Additive modifiers (confidence += 0.20, 0.15, ...)
    │     → Sets df['signal'], df['direction'], df['confidence']
    │     → Sets df['conf_base'], df['conf_fvg'], etc. (breakdown)
    │     → Returns DataFrame
    │
    ├─ Extract last row: if signal==1 and confidence >= threshold:
    │     → Build SetupSignal with entry, SL, TP
    │     → Return (signal, df) tuple
    │
    └─ If no signal: return (None, None)
        │
        ▼
serialize_context(df, signal_idx=len(df)-1)
    → Extracts active zones (fvg_active, ob_active, sr_active)
    → Extracts indicator snapshots (rsi, ema_50, atr, ...)
    → Extracts event states (choch_bullish_recent, ...)
    → Extracts confidence breakdown (conf_base, conf_fvg, ...)
    → Returns JSON dict
        │
        ▼
signal.context_data = context
WatchingManager.create_or_update_setup(session_id, signal)
    → Persists to watching_setups table with context_data JSON
    → SSE event to frontend
```

### Flow 2: Zone Extraction State Machine

```
extract_fvgs(df)                    extract_order_blocks(df)
        │                                    │
        ▼                                    ▼
For each 3-candle window:            For each bearish candle (OB candidate):
  if C3.low > C1.high → bullish       count consecutive bullish after it
  if C3.high < C1.low → bearish        verify impulse length >= 2
        │                              verify ATR displacement >= 1.5
        ▼                              verify BOS (break of structure)
_apply_fvg_zone(df, idx, ...)               │
        │                                    ▼
Step 1: Set at formation candle      _apply_ob_zone(df, idx, ...)
        fvg_upper=103, lower=102             │
        │                            Same 5-step state machine
Step 2: ffill() from idx onward      but with body-close mitigation
        zone persists across time           │
        │                                    ▼
Step 3: Shift active by +1           ob_active = True at idx+1
        fvg_active[idx+1:] = True    ob dies when close < ob_low (bullish)
        │                            or close > ob_upper (bearish)
Step 4: Mitigation kill-switch
        if direction=='bullish':
          mitigated = low <= lower
        else:
          mitigated = high >= upper
        │
Step 5: NaN on mitigation
        df.loc[mitigated] = NaN
        fvg_active = False
        All future rows also NaN'd
```

### Flow 3: Confidence Scoring Matrix (Pattern for Strategy Rewrites)

```python
def generate_signals(self, df):
    # ── HARD GATE: Must be true ──
    base_setup = df['ob_active'] & (df['close'] > df['ema_200'])

    # ── BASE CONFIDENCE ──
    df['confidence'] = np.where(base_setup, 0.50, 0.0)
    df['conf_base'] = df['confidence'].copy()

    # ── ADDITIVE MODIFIERS (soft gates) ──
    fvg_overlap = df['fvg_active'].notna() & (df['fvg_lower'] <= df['ob_upper'])
    df['conf_fvg'] = np.where(base_setup & fvg_overlap, 0.20, 0.0)
    df['confidence'] += df['conf_fvg']

    rsi_ok = df['rsi'].notna() & (df['rsi'] < 30)
    df['conf_rsi'] = np.where(base_setup & rsi_ok, 0.15, 0.0)
    df['confidence'] += df['conf_rsi']

    # ... more modifiers ...

    # ── TRIGGER ──
    df['signal'] = np.where(df['confidence'] >= self.min_confidence, 1, 0)
    df['direction'] = np.where(df['signal'] == 1, 'LONG', None)
    return df
```

---

## Part 4: Verification Procedure

### Step 1: Confirm All Imports Resolve

```bash
cd backend
python3 -c "
from app.core.indicators import compute_ema, compute_rsi, compute_macd, compute_bollinger, compute_atr
from app.core.indicator_service import IndicatorService
from app.core.data_utils import get_finalized_candles, StaleDataError
from app.core.market_structure import extract_fvgs, extract_order_blocks
from app.core.events import detect_choch, detect_volume_climax, detect_liquidity_sweep
from app.core.context_serializer import serialize_context
from app.core.fractals import detect_swing_points_df, build_swing_list
from app.core.base_strategy import BaseStrategy, safe_lt, safe_gt, safe_between
from app.core.sr_engine import SREngine
print('All imports OK')
"
```

**Expected**: `All imports OK`

### Step 2: Run All Tests

```bash
cd backend
python3 -m pytest tests/ -v --tb=short
```

**Expected**: 252+ passed, 2 pre-existing failures (`test_single_timeframe_url`, `test_382_level_lower_confidence`).

### Step 3: Verify All 5 New Test Suites Pass Individually

```bash
cd backend
python3 -m pytest tests/test_extract_fvgs.py -v
python3 -m pytest tests/test_extract_order_blocks.py -v
python3 -m pytest tests/test_extract_events.py -v
python3 -m pytest tests/test_invalidation_scenarios.py -v
```

**Expected**: All 35 new tests pass.

### Step 4: Run the Extraction Layer Audit

```bash
cd backend
python3 scripts/audit_extraction_code.py app/core/market_structure.py app/core/events.py app/core/indicators.py app/core/fractals.py app/core/sr_engine.py
```

**Expected**: `5/5 clean, 0 violations`

### Step 5: End-to-End v2 Pipeline Test

```bash
cd backend
python3 -c "
import pandas as pd, numpy as np
from app.core.base_strategy import BaseStrategy
from app.core.strategy_runner import StrategyRunner

# Create a test strategy using the v2 pipeline
class TestConfluenceStrategy(BaseStrategy):
    name = 'Test Confluence'
    timeframes = ['1h']
    min_confidence = 0.70
    required_features = ['ema', 'rsi', 'atr', 'fvg'] 
    feature_config = {'ema_periods': [9, 21, 50], 'rsi_period': 14, 'atr_period': 14}
    
    def generate_signals(self, df):
        # Base: EMA 9 > EMA 21
        base_setup = df['ema_9'] > df['ema_21']
        df['confidence'] = np.where(base_setup, 0.50, 0.0)
        df['conf_base'] = df['confidence'].copy()
        
        # Modifier 1: Close above EMA 50
        df['conf_ema50'] = np.where(base_setup & (df['close'] > df['ema_50']), 0.20, 0.0)
        df['confidence'] += df['conf_ema50']
        
        # Modifier 2: RSI 40-60
        rsi_ok = df['rsi'].notna() & df['rsi'].between(40, 60)
        df['conf_rsi'] = np.where(base_setup & rsi_ok, 0.15, 0.0)
        df['confidence'] += df['conf_rsi']
        
        df['signal'] = np.where(df['confidence'] >= self.min_confidence, 1, 0)
        df['direction'] = np.where(df['signal'] == 1, 'LONG', None)
        return df

# Simulate candles
n = 300
close = 100.0 + np.cumsum(np.random.randn(n) * 0.3)
df = pd.DataFrame({
    'open_time': pd.date_range('2026-01-01', periods=n, freq='1h'),
    'open': close - 0.2, 'high': close + 0.5, 'low': close - 0.5,
    'close': close, 'volume': np.random.uniform(500, 1500, n),
})

strategy = TestConfluenceStrategy()
df = strategy.pre_process(df, symbol='BTCUSDT', timeframe='1h')
df = strategy.generate_signals(df)

signals = df['signal'].sum()
print(f'Signals generated: {signals}')
print(f'Confidence range: [{df.confidence.min():.2f}, {df.confidence.max():.2f}]')
print(f'NaN in confidence: {df.confidence.isna().sum()}')
print(f'NaN in signal: {df.signal.isna().sum()}')

# Verify confidence breakdown columns exist
conf_cols = [c for c in df.columns if c.startswith('conf_')]
print(f'Confidence breakdown columns: {conf_cols}')

# Verify pre_process added expected features
assert 'ema_9' in df.columns, 'ema_9 missing'
assert 'ema_50' in df.columns, 'ema_50 missing'
assert 'rsi' in df.columns, 'rsi missing'
assert 'atr' in df.columns, 'atr missing'
assert 'fvg_active' in df.columns, 'fvg_active missing'

# Verify no NaN in signal/confidence
assert df['confidence'].notna().all(), 'NaN in confidence'
assert df['signal'].notna().all(), 'NaN in signal'

print()
print('E2E v2 pipeline: ALL CHECKS PASSED')
"
```

**Expected**: All checks pass. Signals generated > 0. No NaN in confidence/signal.

### Step 6: Context Serialization Verification

```bash
cd backend
python3 -c "
import pandas as pd, numpy as np
from app.core.context_serializer import serialize_context

# Build a mock pre-processed DataFrame
df = pd.DataFrame({
    'open_time': pd.date_range('2026-05-01', periods=10, freq='1h'),
    'open': [100.0]*10, 'high': [101.0]*10, 'low': [99.0]*10,
    'close': [100.5]*10, 'volume': [1000.0]*10,
    'fvg_active': [True]*10, 'fvg_upper': [103.0]*10, 'fvg_lower': [102.0]*10,
    'fvg_volume': [1500.0]*10, 'fvg_created_at': pd.date_range('2026-05-01', periods=10, freq='1h'),
    'ob_active': [True]*10, 'ob_upper': [101.5]*10, 'ob_lower': [100.0]*10,
    'ob_direction': ['bullish']*10,
    'sr_active': [True]*10, 'sr_support_upper': [99.0]*10, 'sr_support_lower': [98.5]*10,
    'sr_support_strength': [0.65]*10,
    'rsi': [45.0]*10, 'ema_50': [101.0]*10, 'atr': [0.5]*10,
    'event_choch_bullish_recent': [True]*10,
    'conf_base': [0.50]*10, 'conf_fvg': [0.20]*10, 'conf_rsi': [0.15]*10,
    'signal': [0]*9 + [1], 'direction': [None]*9 + ['LONG'],
    'confidence': [0.0]*9 + [0.85],
})

context = serialize_context(df, signal_idx=9)
print('Context keys:', list(context.keys()))
print('Active zones:', list(context['active_zones'].keys()))
print('Indicators:', list(context['indicators'].keys())[:5], '...')
print('Events:', list(context['events'].keys()))
print('Confidence breakdown:', context['confidence_breakdown'])
print('Candle:', context['candle'])

# Verify expected structure
assert 'active_zones' in context
assert 'indicators' in context
assert 'events' in context
assert 'confidence_breakdown' in context
assert context['confidence_breakdown']['total'] == 0.85
assert context['active_zones']['fvg']['upper'] == 103.0

print()
print('Context serialization: ALL CHECKS PASSED')
"
```

**Expected**: All checks pass. Context dict has expected keys and values.

### Step 7: Verify Backward Compatibility

The existing 13 strategy files still use the legacy `scan()` interface. Confirm they still work:

```bash
cd backend
python3 -m pytest tests/test_strategies.py tests/test_strategy_runner.py -v
```

**Expected**: All legacy tests pass (except pre-existing `test_382_level_lower_confidence`).

---

## Part 5: Known Pre-Existing Failures (Not Introduced by These Changes)

| Test | Issue | Cause |
|------|-------|-------|
| `test_single_timeframe_url` | AssertionError on Binance URL format | Binance API URL changed from `stream?streams=` to `market/stream?streams=` |
| `test_382_level_lower_confidence` | Signal is None when expected | Strategy threshold/config mismatch with test data |

---

## Part 6: What's NOT Yet Done (Phase 2 Strategy Rewrites)

The 13 strategy files in `app/strategies/` still use the legacy `scan()` method with `Candle` and `Indicators` dataclasses. They have NOT been rewritten to `generate_signals(df)` with the weighted scoring matrix.

This is the remaining Phase 2 work:
- Convert each strategy from `scan()` → `generate_signals(df)`
- Add `required_features` and `feature_config` to each strategy class
- Implement the base + additive modifiers pattern
- Add confidence breakdown (`conf_*`) columns
- Set `df['direction']` explicitly for each signal row

The infrastructure (BaseStrategy, StrategyRunner v2, context serializer) is ready. The strategies just need their logic ported.
