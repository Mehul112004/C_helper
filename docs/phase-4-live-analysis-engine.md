# Phase 4: Live Analysis Engine & Watching Cards

## Goal
Live market scanning running. Watching cards appearing in the UI.

## Tasks Breakdown

### 1. Live Data Ingestion
- Implement `utils/binance.py` Binance WebSocket client handling live price streams and candle updates.
- Parse continuous WebSocket messages to detect live candle closes.

### 2. Core Scanning Engine
- Implement `core/scanner.py` to trigger the active strategies' `scan()` methods whenever a tracked candle closes.
- Create standard logic to start and stop analysis sessions securely (maximum 2 simultaneous sessions).

### 3. Watching Setup Lifecycle Manager
- Implement the "setup detected -> watching card" logic.
- Record setups matching trigger conditions, saving them internally with associated expiry checks (e.g., discard after 3 candle closes).
- Forward updates via Server-Sent Events (SSE) to prevent constant client-side polling.

### 4. Signal Feed UI Update
- Enhance the React frontend `SignalFeed` with two tabs: Watching and Confirmed.
- Implement SSE listeners in React to populate the "Watching" tab dynamically as the backend detects setups.
- Add small visual representations (e.g., mini charts) for each watching card.

## Final Deliverable
Users can start a live analysis session in the UI, and watching cards automatically appear/disappear as setups are identified and expire.

## Phase 4 Transition Checklist
- [ ] Live Binance WebSocket streams parse and close candles properly
- [ ] Analysis sessions can be instantiated with chosen symbols and strategies
- [ ] Active sessions properly spawn watching cards inside the React UI via SSE
- [ ] Watching cards accurately expire upon missed target candles
