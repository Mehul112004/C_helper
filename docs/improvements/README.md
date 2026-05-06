# MTF Architecture Refactoring — Phase Index

Multi-Timeframe (MTF) engine refactoring broken into 7 independently shippable phases.

## Phase Overview

| Phase | Name | Files Changed | Risk | Depends On |
|-------|------|---------------|------|------------|
| 1 | [Base Contracts & Data Structures](phase-1-base-contracts.md) | 2 new, 1 modified | Low | — |
| 2 | [Zone Manager & Strategy Runner](phase-2-zone-manager.md) | 1 new, 1 modified | Low | Phase 1 |
| 3 | [Scanner Split Streams](phase-3-scanner-split.md) | 1 modified | **High** | Phase 1, 2 |
| 4 | [Backtest Engine MTF Merge](phase-4-backtest-engine.md) | 2 modified | **High** | Phase 1 |
| 5 | [Strategy Migration — Group A (ON_CLOSE)](phase-5-group-a-strategies.md) | 5 modified | Medium | Phase 1, 2, 3 |
| 6 | [Strategy Migration — Group B & C](phase-6-group-bc-strategies.md) | 8 modified | Medium | Phase 1, 2, 3 |
| 7 | [LLM Dual-Context & Loader](phase-7-llm-and-loader.md) | 3 modified | Low | Phase 1, 6 |

## Execution Rules

1. **Each phase must leave the system fully functional.** No half-broken states between phases.
2. **Legacy `scan()` works at all times.** Un-migrated strategies continue using the old path.
3. **One strategy at a time within Phase 5/6.** Each strategy migration is an independent commit.
4. **Run existing tests after every phase.** No regressions allowed.

## Resolved Design Decisions

- **HTF Timeframe Mapping**: Strategies declare `context_tf`/`execution_tf`; scanner `DEFAULT_HTF_MAP` is fallback.
- **ON_TOUCH Granularity**: Fire on every WebSocket tick (throttled 500ms per strategy/symbol).
- **Zone Expiry**: Re-compute when `context_tf` candle closes (natural refresh cycle).
- **Backtest Versioning**: Add `engine_version` column to `BacktestRun`.
