# Phase 7: Backtesting Engine

## Goal
Any strategy can be backtested against historical data with full metrics and charts.

## Tasks Breakdown

### 1. Vectorized Overhaul
- Implement the core engine leveraging heavily vectorized pandas operations rather than simple loop iteration to allow extremely fast historical testing (years of 5m data in seconds).

### 2. Outcome Calculations
- Utilize the same S/R identification logic and basic SL/TP logic implemented in the live scanner to guarantee 1:1 strategy replication.
- Create mathematical evaluators computing vital metrics: Win Rate, Total PnL, Max Drawdown, Sharpe/Sortino Ratios, and Profit Factor.

### 3. Backend Backtesting Endpoint
- Establish `/api/backtest` accepting varied test configurations (e.g., symbol combinations, capital, risk %, date range).
- Ensure output payloads comprehensively pack both equity curve generation arrays and deep trade logs.

### 4. Backtest Frontend Features
- Build out the Configuration Panel and Results Summary Metrics within the `Backtest` React page.
- Render the Equity Curve and specialized Trade Chart employing Lightweight Charts from TradingView.
- Supply a detailed HTML/React table exhibiting exact trade logs containing robust sorting and CSV export functionality.

## Final Deliverable
Users can flawlessly test newly authored strategies or core built-in ones across huge historical frames returning in-depth analytical reporting.

## Phase 7 Transition Checklist
- [ ] Vectorized python execution verifies high performance across long spans
- [ ] Output metrics correctly map accurate R/R, Win rate, and PnL ratios
- [ ] Visual React tables fully compile trade records completely inline with backend outputs
- [ ] Equity Curve populates correctly within TradingView Lightweight Charts
