"""
LLM Context Builder — Structured Multi-Dimensional Payload

Builds a clean Python dict with 5 dimensions for the LLM to evaluate:
  1. Market Structure & Narrative
  2. Multi-Timeframe Context
  3. Momentum & Indicator Confluence
  4. Volume & Order Flow
  5. Recent Price Action (compressed OHLCV)

Everything is extracted from the pre-processed DataFrame — no more
Candle/Indicators objects. The builder handles missing columns gracefully.
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, Any, List


def build_llm_context(
    df: pd.DataFrame,
    signal: dict,  # SetupSignal.to_dict() or equivalent
    symbol: str,
    htf_data: Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, Any]:
    """
    Build the complete structured payload for LLM evaluation.

    Args:
        df: Pre-processed DataFrame from strategy.pre_process() + generate_signals()
        signal: Dict with keys: strategy_name, timeframe, direction, entry, sl, tp1, tp2, confidence
        symbol: Trading pair (e.g. 'BTCUSDT')
        htf_data: Optional dict mapping timeframe string → pre-processed DataFrame
                  e.g. {'1h': df_1h, '4h': df_4h}

    Returns:
        Dict with 5 top-level keys: signal_metadata, market_structure,
        indicators, volume, htf_context, recent_price_action
    """
    last = df.iloc[-1]
    direction = signal.get('direction', 'LONG')

    payload = {
        "signal_metadata": _build_signal_metadata(signal, symbol),
        "market_structure": _build_market_structure(df),
        "indicators": _build_indicators(df, direction),
        "volume": _build_volume_profile(df),
        "htf_context": _build_htf_context(df, htf_data),
        "recent_price_action": _build_recent_candles(df, n=20),
    }

    return payload


# ═══════════════════════════════════════════════════════════════
#  Dimension 1: Signal Metadata
# ═══════════════════════════════════════════════════════════════

def _build_signal_metadata(signal: dict, symbol: str) -> dict:
    return {
        "symbol": symbol,
        "strategy": signal.get('strategy_name', 'Unknown'),
        "timeframe": signal.get('timeframe', '1h'),
        "side": signal.get('direction', 'LONG'),
        "entry": signal.get('entry'),
        "sl": signal.get('sl'),
        "tp1": signal.get('tp1'),
        "tp2": signal.get('tp2'),
        "confidence": round(signal.get('confidence', 0), 3),
        "regime": signal.get('regime', 'UNKNOWN'),
    }


# ═══════════════════════════════════════════════════════════════
#  Dimension 2: Market Structure & Narrative
# ═══════════════════════════════════════════════════════════════

def _build_market_structure(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    result = {}

    # Regime / bias
    result["current_bias"] = str(last.get('regime', 'UNKNOWN'))
    result["structural_bias"] = str(last.get('structural_bias', 'NEUTRAL'))
    result["regime_strength"] = round(float(last.get('regime_strength', 0)), 2)

    # Break of Structure / Change of Character
    if 'event_bos_bullish_recent' in df.columns:
        has_bos_bull = last.get('event_bos_bullish_recent', False)
        has_bos_bear = last.get('event_bos_bearish_recent', False)
        has_choch_bull = last.get('event_choch_bullish_recent', False)
        has_choch_bear = last.get('event_choch_bearish_recent', False)

        if has_choch_bull or has_choch_bear:
            result["last_event"] = "CHoCH"
        elif has_bos_bull or has_bos_bear:
            result["last_event"] = "BOS"
        else:
            result["last_event"] = "None"

        result["recent_events"] = {
            "bos_bullish": bool(has_bos_bull),
            "bos_bearish": bool(has_bos_bear),
            "choch_bullish": bool(has_choch_bull),
            "choch_bearish": bool(has_choch_bear),
        }
    else:
        result["last_event"] = "N/A"

    # Liquidity sweep
    if 'event_sweep_recent' in df.columns:
        result["liquidity_sweep_recent"] = bool(last.get('event_sweep_recent', False))
        result["sweep_bullish"] = bool(last.get('event_sweep_bullish', False))
        result["sweep_bearish"] = bool(last.get('event_sweep_bearish', False))
    else:
        result["liquidity_sweep_recent"] = False

    # Order blocks
    if 'ob_active' in df.columns and last.get('ob_active'):
        result["nearest_order_block"] = {
            "active": True,
            "upper": float(last['ob_upper']) if pd.notna(last.get('ob_upper')) else None,
            "lower": float(last['ob_lower']) if pd.notna(last.get('ob_lower')) else None,
            "direction": str(last.get('ob_direction', 'N/A')),
        }
        # Distance from current price to OB
        if pd.notna(last.get('ob_upper')) and pd.notna(last.get('ob_lower')):
            price = float(last['close'])
            ob_mid = (float(last['ob_upper']) + float(last['ob_lower'])) / 2
            result["distance_to_ob_pct"] = round(abs(price - ob_mid) / price * 100, 2)
    else:
        result["nearest_order_block"] = {"active": False}

    # Fair Value Gaps
    if 'fvg_active' in df.columns and last.get('fvg_active'):
        result["fvg_status"] = "Active"
        fvg_upper = float(last['fvg_upper']) if pd.notna(last.get('fvg_upper')) else None
        fvg_lower = float(last['fvg_lower']) if pd.notna(last.get('fvg_lower')) else None
        if fvg_upper and fvg_lower:
            price = float(last['close'])
            if price > fvg_upper:
                result["fvg_position"] = "Below_Price"
            elif price < fvg_lower:
                result["fvg_position"] = "Above_Price"
            else:
                result["fvg_position"] = "Inside_Price"
    else:
        result["fvg_status"] = "None"

    # Swing levels (from rolling pivots)
    result["recent_swing_high"] = round(float(df['high'].rolling(20).max().iloc[-1]), 2)
    result["recent_swing_low"] = round(float(df['low'].rolling(20).min().iloc[-1]), 2)
    result["current_price"] = round(float(last['close']), 2)

    # Price position relative to swing range
    swing_range = result["recent_swing_high"] - result["recent_swing_low"]
    if swing_range > 0:
        pos = (result["current_price"] - result["recent_swing_low"]) / swing_range
        result["price_position_in_range_pct"] = round(pos * 100, 1)

    return result


# ═══════════════════════════════════════════════════════════════
#  Dimension 3: Momentum & Indicator Confluence
# ═══════════════════════════════════════════════════════════════

def _build_indicators(df: pd.DataFrame, direction: str) -> dict:
    last = df.iloc[-1]
    result = {}

    # RSI
    if 'rsi' in df.columns and pd.notna(last.get('rsi')):
        rsi_val = float(last['rsi'])
        result["rsi"] = round(rsi_val, 1)

        # RSI gradient (last 5 bars)
        rsi_5_ago = float(df['rsi'].iloc[-5]) if len(df) >= 5 and pd.notna(df['rsi'].iloc[-5]) else rsi_val
        result["rsi_gradient"] = _gradient_label(rsi_5_ago, rsi_val, threshold=2.0)

        # RSI divergence detection
        result["rsi_divergence"] = _detect_rsi_divergence(df)
    else:
        result["rsi"] = None
        result["rsi_gradient"] = "N/A"
        result["rsi_divergence"] = "N/A"

    # EMA alignment
    ema_cols = [c for c in ['ema_9', 'ema_20', 'ema_50', 'ema_200'] if c in df.columns]
    if len(ema_cols) >= 2:
        ema_values = {c: float(last[c]) for c in ema_cols if pd.notna(last.get(c))}
        result["ema_values"] = {k: round(v, 2) for k, v in ema_values.items()}

        # Check perfect order
        prices = [float(last[c]) for c in ema_cols if pd.notna(last.get(c))]
        if len(prices) >= 3:
            if all(prices[i] > prices[i+1] for i in range(len(prices)-1)):
                result["ema_alignment"] = "Bullish_Perfect_Order"
            elif all(prices[i] < prices[i+1] for i in range(len(prices)-1)):
                result["ema_alignment"] = "Bearish_Perfect_Order"
            else:
                result["ema_alignment"] = "Mixed"
        else:
            result["ema_alignment"] = "Insufficient_Data"
    else:
        result["ema_alignment"] = "N/A"

    # MACD
    if 'macd_histogram' in df.columns and pd.notna(last.get('macd_histogram')):
        macd_hist = float(last['macd_histogram'])
        macd_hist_prev = float(df['macd_histogram'].iloc[-2]) if len(df) >= 2 and pd.notna(df['macd_histogram'].iloc[-2]) else macd_hist
        result["macd"] = {
            "histogram": round(macd_hist, 4),
            "momentum": "Accelerating" if abs(macd_hist) > abs(macd_hist_prev) else "Decelerating",
            "direction": "Bullish" if macd_hist > 0 else "Bearish",
        }
    else:
        result["macd"] = None

    # Bollinger Bands
    if 'bb_width' in df.columns and pd.notna(last.get('bb_width')):
        bbw = float(last['bb_width'])
        bbw_avg = float(df['bb_width'].rolling(20).mean().iloc[-1]) if len(df) >= 20 else bbw
        if bbw > bbw_avg * 1.2:
            result["bb_state"] = "Expanding"
        elif bbw < bbw_avg * 0.8:
            result["bb_state"] = "Squeezing"
        else:
            result["bb_state"] = "Normal"

        if 'bb_upper' in df.columns and 'bb_lower' in df.columns:
            price = float(last['close'])
            bb_upper = float(last['bb_upper'])
            bb_lower = float(last['bb_lower'])
            if pd.notna(bb_upper) and pd.notna(bb_lower) and (bb_upper - bb_lower) > 0:
                result["bb_position_pct"] = round((price - bb_lower) / (bb_upper - bb_lower) * 100, 1)
    else:
        result["bb_state"] = "N/A"

    # ATR
    if 'atr' in df.columns and pd.notna(last.get('atr')):
        result["atr"] = round(float(last['atr']), 4)

    # ADX trend strength
    if 'adx' in df.columns and pd.notna(last.get('adx')):
        adx_val = float(last['adx'])
        result["adx"] = round(adx_val, 1)
        if adx_val >= 25:
            result["trend_strength"] = "Strong"
        elif adx_val >= 20:
            result["trend_strength"] = "Moderate"
        else:
            result["trend_strength"] = "Weak/None"
    else:
        result["trend_strength"] = "N/A"

    return result


# ═══════════════════════════════════════════════════════════════
#  Dimension 4: Volume & Order Flow
# ═══════════════════════════════════════════════════════════════

def _build_volume_profile(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    result = {}

    current_vol = float(last['volume'])

    if 'volume_ma' in df.columns and pd.notna(last.get('volume_ma')):
        vol_ma = float(last['volume_ma'])
        result["rvol"] = round(current_vol / vol_ma, 2) if vol_ma > 0 else 1.0
    else:
        result["rvol"] = 1.0

    # Volume climax
    if 'event_volume_climax' in df.columns:
        result["is_climax"] = bool(last.get('event_volume_climax', False))
    else:
        result["is_climax"] = False

    # Volume trend (last 5 bars)
    recent_vol = df['volume'].iloc[-5:].mean() if len(df) >= 5 else current_vol
    vol_ma_20 = df['volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else current_vol
    if vol_ma_20 > 0:
        result["volume_vs_recent"] = round(recent_vol / vol_ma_20, 2)

    return result


# ═══════════════════════════════════════════════════════════════
#  Dimension 5: Multi-Timeframe Context
# ═══════════════════════════════════════════════════════════════

def _build_htf_context(
    df: pd.DataFrame,
    htf_data: Optional[Dict[str, pd.DataFrame]] = None,
) -> dict:
    result = {}

    # Primary (self) timeframe
    last = df.iloc[-1]
    if 'ema_50' in df.columns and pd.notna(last.get('ema_50')):
        result["primary_bias"] = "Bullish" if float(last['close']) > float(last['ema_50']) else "Bearish"

    # Higher timeframes from htf_data
    if htf_data:
        for tf_name, htf_df in htf_data.items():
            if htf_df is None or len(htf_df) < 2:
                continue
            htf_last = htf_df.iloc[-1]
            bias = "Neutral"
            if 'ema_50' in htf_df.columns and pd.notna(htf_last.get('ema_50')):
                bias = "Bullish" if float(htf_last['close']) > float(htf_last['ema_50']) else "Bearish"

            ema_stack = "Mixed"
            if all(c in htf_df.columns for c in ['ema_9', 'ema_20', 'ema_50']):
                e9, e20, e50 = float(htf_last['ema_9']), float(htf_last['ema_20']), float(htf_last['ema_50'])
                if pd.notna(e9) and pd.notna(e20) and pd.notna(e50):
                    if e9 > e20 > e50:
                        ema_stack = "Bullish_Stacked"
                    elif e9 < e20 < e50:
                        ema_stack = "Bearish_Stacked"

            key = f"{tf_name}_bias"
            result[key] = bias
            result[f"{tf_name}_ema_stack"] = ema_stack

    return result


# ═══════════════════════════════════════════════════════════════
#  Dimension 6: Recent Price Action (compressed OHLCV)
# ═══════════════════════════════════════════════════════════════

def _build_recent_candles(df: pd.DataFrame, n: int = 20) -> List[Dict]:
    recent = df.iloc[-n:] if len(df) >= n else df
    candles = []
    for _, row in recent.iterrows():
        candles.append({
            "o": round(float(row['open']), 2),
            "h": round(float(row['high']), 2),
            "l": round(float(row['low']), 2),
            "c": round(float(row['close']), 2),
            "v": round(float(row['volume']), 2),
            "t": str(row.get('open_time', ''))[:19] if pd.notna(row.get('open_time')) else "",
        })
    return candles


# ═══════════════════════════════════════════════════════════════
#  Utility helpers
# ═══════════════════════════════════════════════════════════════

def _gradient_label(prev: float, curr: float, threshold: float = 2.0) -> str:
    """Classify the direction of change between two values."""
    diff = curr - prev
    if diff > threshold:
        return "Rising"
    elif diff < -threshold:
        return "Falling"
    return "Flat"


def _detect_rsi_divergence(df: pd.DataFrame) -> str:
    """Detect bullish or bearish RSI divergence over last 20 bars."""
    if 'rsi' not in df.columns or len(df) < 20:
        return "N/A"

    rsi = df['rsi']
    close = df['close']

    # Last 10 bars vs 10-20 bars ago
    recent_close_high = close.iloc[-10:].max()
    older_close_high = close.iloc[-20:-10].max()
    recent_rsi_high = rsi.iloc[-10:].max()
    older_rsi_high = rsi.iloc[-20:-10].max()

    recent_close_low = close.iloc[-10:].min()
    older_close_low = close.iloc[-20:-10].min()
    recent_rsi_low = rsi.iloc[-10:].min()
    older_rsi_low = rsi.iloc[-20:-10].min()

    # Bearish divergence: price higher high, RSI lower high
    if recent_close_high > older_close_high and recent_rsi_high < older_rsi_high:
        return "Bearish"
    # Bullish divergence: price lower low, RSI higher low
    if recent_close_low < older_close_low and recent_rsi_low > older_rsi_low:
        return "Bullish"

    # Hidden bullish: price higher low, RSI lower low
    if recent_close_low > older_close_low and recent_rsi_low < older_rsi_low:
        return "Hidden_Bullish"
    # Hidden bearish: price lower high, RSI higher high
    if recent_close_high < older_close_high and recent_rsi_high > older_rsi_high:
        return "Hidden_Bearish"

    return "None"
