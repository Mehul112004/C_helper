# Phase 2: Indicator Engine & S/R Zone Detection

## Goal
All indicators computed on stored candles. S/R zones detected and stored.

## Tasks Breakdown

### 1. Indicator Computation Service
- Create `core/indicators.py` to handle pandas/numpy-based calculations for technical indicators.
- Implement EMA (9, 21, 50, 200), RSI (14), MACD (12/26/9), Bollinger Bands (20/2), ATR (14), and Volume MA.
- Ensure indicators are computed and cached efficiently upon a candle close event, optimizing to prevent full recalculation on every request.

### 2. S/R Zone Detection Engine
- Create `core/sr_engine.py`.
- Implement detection logic leveraging swing highs/lows (with a configurable lookback), round psychological numbers, and previous day/week highs and lows.
- Apply a strength scoring mechanism to zones based on historical touches and timeframe weighting (e.g., 1D zones weigh more than 4h zones).

### 3. Background Refresh Scheduler
- Construct a task scheduler to recalculate and refresh S/R zones fully every 4h candle close.
- Add logic for minor zone updates (like new swing points) on every 1h candle close.

### 4. API Endpoints
- Implement `/api/indicators` and `/api/sr-zones` in the designated blueprint to serve pre-calculated data to the frontend or other services.
- **Deliverable**: Standardized endpoints for cleanly fetching technical data.

## Final Deliverable
For any available symbol and timeframe, technical indicators and structured S/R zones are computable, cached, and available via API.

## Phase 2 Transition Checklist
- [ ] EMA, RSI, MACD, Bollinger Bands, and ATR calculations verified against known data
- [ ] Indicators cache correctly upon candle close
- [ ] S/R zones correctly identified mathematically from swing points
- [ ] Zone background refresh scheduler executes at 4h intervals mapping real time
- [ ] API endpoints return structured indicator and S/R zone payloads
