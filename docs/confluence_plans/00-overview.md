# Confluence Engine Restructuring — Master Plan

## Purpose

This document is the architectural blueprint for a major restructuring of the C_helper backend. The goal is to separate mathematical feature extraction from strategy logic, replacing rigid boolean AND-gate strategies with a weighted scoring confluence engine.

## Current State vs. Target State

| Dimension | Current | Target |
|-----------|---------|--------|
| **Indicator Math** | `IndicatorService` in `app/core/` | `app/core/indicators.py` (purified, contract-enforced) |
| **Market Structure (FVG/OB)** | Embedded in strategy files | `app/core/market_structure.py` (extraction layer) |
| **S/R Zones** | `app/core/sr_engine.py` (mixed concerns) | `app/core/sr_engine.py` (purified, universal zone contract) |
| **Temporal Events (ChoCh/BOS)** | Embedded in `smc_structure_shift.py` | `app/core/events.py` (boolean masks + rolling memory) |
| **Strategies** | Monolithic `scan()` doing math + logic | Logic gates + confidence scoring only |
| **Signal Generation** | Single boolean `scan()` return | Weighted scoring matrix with base requirements + additive modifiers |
| **Data Persistence** | Live row data in DB | Snapshot pattern: JSON context_data on signal rows |

## Phase Dependency Graph

```
Phase 1 (Feature Extraction Layer)
  ├── 1a: Continuous State (indicators.py)
  ├── 1b: Spatial State (market_structure.py + sr_engine.py)
  └── 1c: Temporal State (events.py)
        │
        ▼
Phase 2 (Confluence Engine)
  ├── BaseStrategy → orchestrator refactor
  └── Strategy scoring matrix pattern
        │
        ▼
Phase 3 (State Persistence)
  ├── Snapshot serialization
  └── DB contract (context_data JSON)
        │
        ▼
Phase 4 (Defensive Coding)
  ├── Forward-fill leak fix
  ├── Lookahead bias fix
  ├── Mitigation desync fix
  ├── NaN propagation fix
  └── Vectorization optimization
        │
        ▼
Phase 5 (Validation)
  ├── Extractor isolation tests
  ├── TradingView manual verification
  └── Invalidation test suite
```

## Trap Mitigation Map

| Trap | Phase Addressed | Key Fix |
|------|----------------|---------|
| T1: Live Candle Poisoning | Phase 1, 4 | `get_finalized_candles()` excludes `is_closed=False` + staleness guard |
| T2: Gap-Heal Race Condition | Phase 1, 4 | Blocking gap heal before extractor pipeline; abort on failure |
| T3: Lookback Horizon Leak | Phase 2 | `get_required_lookback()` per feature set (spatial=1000, ema200=300) |
| T4: Intra-candle Invalidation | Phase 3 | Accept latency; invalidate on candle close only |
| T5: ffill Contradiction | Phase 1, 4 | Masked ffill: ffill for persistence, mitigation mask for death |
| T6: Overlapping Zone Overwrite | Phase 1 | Single-zone V1 contract: track only most recently formed unmitigated zone |
| T7: Event Memory Cancellation | Phase 1 | Opposing events zero out counterpart's `_recent` memory |
| T8: DB Staleness | Phase 1 | `StaleDataError` raised when last closed candle > 2x timeframe old |
| T9: Backtesting Time-Leak | Phase 1 | `get_finalized_candles()` accepts `as_of_ms` parameter; backtester injects simulated time, staleness guard disabled in date-range mode |

## Files to Create / Modify

### New Files
| File | Purpose |
|------|---------|
| `app/core/market_structure.py` | FVG + Order Block extraction |
| `app/core/events.py` | ChoCh, BOS, Volume Climax temporal events |

### Heavily Modified Files
| File | Change |
|------|--------|
| `app/core/indicators.py` | Contract enforcement, NaN policy |
| `app/core/sr_engine.py` | Universal zone contract alignment |
| `app/core/base_strategy.py` | Orchestrator refactor, `pre_process()`, `required_features` |
| `app/strategies/*.py` | All 13 strategies rewritten to use scoring matrix |

### Lightly Modified Files
| File | Change |
|------|--------|
| `app/models/db.py` | Add `context_data` JSON column to signals; add `is_closed` to candles |
| `app/core/scanner.py` | `_on_candle_close()` pipeline update |
| `app/utils/binance.py` | Add finalized candle fetch utility |

## Universal Contracts (Non-Negotiable)

### Zone Contract
Every zone-producing function MUST append these columns to the DataFrame:
```
{prefix}_active:   Boolean
{prefix}_upper:    Float
{prefix}_lower:    Float
{prefix}_volume:   Float (optional)
{prefix}_created_at: Datetime
```

### Continuous State Contract
Every indicator function:
- Input: `(df, period)`
- Output: `pd.Series` of raw floats
- No boolean logic, no NaN propagation to unrelated columns

### Temporal Event Contract
Every event function:
- Output: Boolean mask on the exact trigger candle
- Plus rolling memory column (e.g., `_recent` via `rolling(window=10).max()`)

## Execution Order

1. Phase 1 first — the extraction layer must exist and be validated before anything depends on it
2. Phase 4 defensives must be baked into Phase 1 from day one (not retrofitted)
3. Phase 5 validation gates each phase before the next begins
4. Phase 2 (strategies) is the LAST thing to touch — strategies consume a stable API
