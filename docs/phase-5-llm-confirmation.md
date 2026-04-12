# Phase 5: LLM Confirmation Pipeline & Confirmed Signals

## Goal
Candidate signals flow through LLM, confirmed signals appear in UI.

## Tasks Breakdown

### 1. LLM Client Integration
- Implement `core/llm_client.py` adhering to the LM Studio HTTP endpoint (`http://localhost:1234/v1/chat/completions`).
- Structure the context builder logic: pack recent OHLCV, indicators, S/R zones, and SetupSignal JSON into a defined prompt template.
- Use a deterministic temperature (e.g., 0.2) to guide model outputs.

### 2. Response Parsing & Asynchronous Checking
- Parse the LLM's structured JSON output for `verdict` (CONFIRM/REJECT/MODIFY), `reasoning`, and modified price levels.
- Wrap this execution in an asynchronous confirmation queue to prevent the main Flask thread from blocking. Includes a 60-second retry loop in case LM Studio is inaccessible.

### 3. Database Persistence
- When a candidate signal is CONFIRMED or MODIFIED, log it extensively in the `signals` database table for historical review.
- Appropriately mark REJECTED setups and remove them from active tracking.

### 4. Frontend Confirmed Feed
- Display fully approved signal cards in the UI's "Confirmed" tab.
- Feature an expandable "Reasoning" badge containing the LLM's plain-text justification.
- Add a top-level LM Studio connection status indicator in the app header.

## Final Deliverable
The local LLM serves as the final judge for generated candidates, properly passing accepted signals to the "Confirmed" tab in the UI.

## Phase 5 Transition Checklist
- [ ] LLM prompt builder correctly aggregates 30-candle contexts + indicators
- [ ] Response parser accurately understands CONFIRM, REJECT, or MODIFY
- [ ] Fallback timeout triggers after 60s of LM Studio unavailability
- [ ] Confirmed signals gracefully populate the "Confirmed" UI feed alongside LLM reasoning
