# Phase 6: Telegram Notifications

## Goal
Confirmed signals and outcome updates sent to Telegram automatically.

## Tasks Breakdown

### 1. Telegram API Client
- Integrate the `python-telegram-bot` standard library (`core/telegram.py`).
- Implement secure retrieval of `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` via environmental variables or the platform settings.

### 2. Message Formatting
- Construct a dedicated message formatter that builds the visual Telegram signal including: Action (LONG/SHORT), Pair, Timeframe, Entry/SL/TP levels, R/R ratio, active strategies, and the LLM execution summary.

### 3. Action Hooks
- Hook the delivery function immediately post-LLM confirmation (when verdict is `CONFIRM` or `MODIFY`).
- Establish listeners monitoring live WebSocket prices. When an active trade reaches SL, TP1, or TP2, a clean follow-up summary is sent via Telegram.

### 4. Reliability Tracking
- Persist the notification delivery state to the database (Sent vs. Failed). Set up a basic retry strategy with up to 3 attempts.

## Final Deliverable
Telegram automatically syncs with the confirmed application, broadcasting trade alerts directly to the user's secured channel.

## Phase 6 Transition Checklist
- [ ] Valid environmental Telegram inputs boot the bot client correctly
- [ ] Confirmed signals construct proper structural Telegram strings
- [ ] Post-trigger messages (Hit TP/SL) successfully fire via real-time stream updates
