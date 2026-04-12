# Phase 3: Strategy Engine & BaseStrategy Contract

## Goal
Strategy system built. Built-in strategies implemented. Strategies produce SetupSignal objects.

## Tasks Breakdown

### 1. Strategy Framework & Contract
- Define `SetupSignal` and `Candle` data classes in `core/base_strategy.py`.
- Implement the abstract base class `BaseStrategy` enforcing the core `scan()` method contract.
- Implement optional overrides like `calculate_sl`, `calculate_tp`, and `should_confirm_with_llm`.

### 2. Strategy Registry
- Build a strategy loader mechanism (`core/strategy_loader.py`) to discover and instantiate available strategies from the `strategies/` directory.
- Allow tracking of enabled/disabled states per strategy through database storage and API.

### 3. Built-in Strategies Implementation
Develop the 6 core strategies shipped with the platform in the `strategies/` directory:
- **EMA Crossover**: Reactive strategy on 15m, 1h, 4h.
- **RSI Reversal**: Reactive strategy on 1h, 4h.
- **Bollinger Band Squeeze**: Reactive strategy on 1h, 4h.
- **MACD Momentum**: Reactive strategy on 1h, 4h, 1D.
- **S/R Zone Rejection**: Conditional strategy on 4h, 1D.
- **S/R Zone Breakout**: Conditional strategy on 1h, 4h.

### 4. Backend Strategy Endpoints & Tests
- Create tests validating the outputs of built-in strategies against subset historical datasets.
- Add an API to manage (enable/disable) strategies per active session.

## Final Deliverable
A robust suite of built-in strategies is able to run against historical data and dynamically generate correct `SetupSignal` objects.

## Phase 3 Transition Checklist
- [ ] BaseStrategy classes correctly mandate scan() methods
- [ ] 6 built-in strategies correctly parse indicators and identify proper setups
- [ ] Output from strategy scans properly forms SetupSignal objects
- [ ] Unit tests for built-in strategies pass on historical data
