from datetime import datetime
from app.models.db import ConfirmedSignal

def format_confirmed_signal(signal: ConfirmedSignal) -> str:
    """
    Format a confirmed trade signal into a structured Telegram message.
    """
    # Emojis based on direction
    direction_badge = "🟢" if signal.direction == "LONG" else "🔴"
    
    # Calculate R/R
    risk = abs(signal.entry - signal.sl)
    reward = abs(signal.tp1 - signal.entry) if risk > 0 else 0
    rr_ratio = reward / risk if risk > 0 else 0
    
    # Time formatting
    if signal.created_at:
        dt = signal.created_at
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        time_str = dt.strftime("%d %b %Y %H:%M UTC")
    else:
        time_str = datetime.utcnow().strftime("%d %b %Y %H:%M UTC")
        
    # Reason formatting
    reasoning = signal.reasoning_text.strip()
    
    msg = f"""
{direction_badge} CONFIRMED SIGNAL

*Pair*      : {signal.symbol}
*Direction* : {signal.direction}
*Timeframe* : {signal.timeframe}
*Entry*     : ${signal.entry:,.4f}
*SL*        : ${signal.sl:,.4f}
*TP1*       : ${signal.tp1:,.4f}
*TP2*       : ${signal.tp2:,.4f}
*R/R*       : 1 : {rr_ratio:.1f}
*Strategy*  : {signal.strategy_name}
*Confidence*: {signal.confidence * 100:.0f}%

*Analysis*  :
{reasoning}

⏱ {time_str}
"""
    return msg.strip()


def format_watching_signal(setup) -> str:
    """
    Format an unconfirmed watching setup into a structured Telegram message.
    """
    direction_badge = "👀 🟢" if setup.direction == "LONG" else "👀 🔴"
    
    if setup.detected_at:
        dt = setup.detected_at
        if isinstance(dt, str):
            from datetime import datetime
            dt = datetime.fromisoformat(dt)
        time_str = dt.strftime("%d %b %Y %H:%M UTC")
    else:
        from datetime import datetime
        time_str = datetime.utcnow().strftime("%d %b %Y %H:%M UTC")
        
    notes = setup.notes.strip() if hasattr(setup, 'notes') and setup.notes else ""
    
    msg = f"""
{direction_badge} WATCHING SCAN (Not Confirmed)

*Pair*      : {setup.symbol}
*Direction* : {setup.direction}
*Timeframe* : {setup.timeframe}
*Strategy*  : {setup.strategy_name}
*Confidence*: {setup.confidence * 100:.0f}%

*Notes*     : 
{notes}

*Status*    : PENDING LLM CONFIRMATION...
⏱ {time_str}
"""
    return msg.strip()


def format_outcome_update(signal: ConfirmedSignal, outcome: str) -> str:
    """
    Format a simple outcome follow-up message when TP1, TP2 or SL is hit.
    """
    if outcome == "HIT_TP1":
        icon = "✅"
        level = signal.tp1
        label = "TP1"
    elif outcome == "HIT_TP2":
        icon = "🚀"
        level = signal.tp2
        label = "TP2"
    elif outcome == "HIT_SL":
        icon = "❌"
        level = signal.sl
        label = "SL"
    elif outcome == "EXPIRED":
        icon = "⏳"
        return f"{icon} {signal.symbol} {signal.direction} — Setup EXPIRED without entry."
    else:
        icon = "ℹ️"
        level = 0.0
        label = outcome
        
    return f"{icon} {signal.symbol} {signal.direction} — {label} hit at ${level:,.4f}"
