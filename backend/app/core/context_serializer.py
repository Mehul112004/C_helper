"""
Context Serializer — Phase 3 Snapshot Pattern

Serializes the exact row state (active zones, indicator values, events,
confidence breakdown) at the moment a signal fires into a JSON-safe dict
for storage in the context_data column.

This feeds the LLM and the frontend without any database recalculations.
"""

import numpy as np
import pandas as pd
from typing import Any, Optional


def _safe_json(val: Any) -> Optional[Any]:
    """Convert numpy/pandas types to JSON-safe Python types."""
    if val is None:
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (pd.Timestamp,)):
        return val.isoformat()
    if isinstance(val, (np.bool_,)):
        return bool(val)
    try:
        if np.isnan(val):
            return None
    except (TypeError, ValueError):
        pass
    return val


def serialize_context(df: pd.DataFrame, signal_idx: int) -> dict:
    """
    Extract snapshot of all active zones, indicators, events, and
    confidence breakdown at the exact candle where a signal fired.

    Args:
        df: Pre-processed DataFrame with all feature columns
        signal_idx: Integer position index where signal == 1

    Returns:
        JSON-serializable dict for context_data column
    """
    row = df.iloc[signal_idx]

    context = {
        'candle': {
            'open_time': str(row['open_time']),
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': float(row['volume']),
        },
        'active_zones': {},
        'indicators': {},
        'events': {},
        'confidence_breakdown': {},
    }

    # ── Active zones (only where _active is True at this row) ──
    _extract_zones(df, row, context)

    # ── Indicator snapshots ──
    indicator_cols = [
        'rsi', 'ema_9', 'ema_21', 'ema_50', 'ema_100', 'ema_200',
        'atr', 'macd_line', 'macd_signal', 'macd_histogram',
        'bb_upper', 'bb_middle', 'bb_lower', 'bb_width',
        'volume_ma',
    ]
    for col in indicator_cols:
        if col in df.columns:
            val = _safe_json(row[col])
            if val is not None:
                context['indicators'][col] = val

    # ── Event states ──
    event_cols = [c for c in df.columns if c.startswith('event_')]
    for col in event_cols:
        val = _safe_json(row.get(col))
        if val is not None:
            context['events'][col] = bool(val)

    # ── Confidence breakdown (Phase 2: conf_* columns) ──
    conf_cols = [c for c in df.columns if c.startswith('conf_')]
    total = 0.0
    for col in conf_cols:
        val = _safe_json(row.get(col))
        if val is not None and isinstance(val, (int, float)) and val > 0:
            label = col.replace('conf_', '')
            context['confidence_breakdown'][label] = float(val)
            total += float(val)
    if total > 0:
        context['confidence_breakdown']['total'] = round(total, 4)

    return context


def _extract_zones(df: pd.DataFrame, row: pd.Series, context: dict):
    """Extract active zone data from the signal row."""
    # FVG zones
    if 'fvg_active' in df.columns and row.get('fvg_active'):
        zone = {}
        for col in ['fvg_upper', 'fvg_lower', 'fvg_volume', 'fvg_created_at']:
            if col in df.columns:
                val = _safe_json(row[col])
                if val is not None:
                    zone[col.replace('fvg_', '')] = val
        if zone:
            context['active_zones']['fvg'] = zone

    # OB zones
    if 'ob_active' in df.columns and row.get('ob_active'):
        zone = {}
        for col in ['ob_upper', 'ob_lower', 'ob_volume', 'ob_direction', 'ob_created_at']:
            if col in df.columns:
                val = _safe_json(row[col])
                if val is not None:
                    zone[col.replace('ob_', '')] = val
        if zone:
            context['active_zones']['ob'] = zone

    # S/R zones
    sr_data = {}
    for col in ['sr_support_upper', 'sr_support_lower', 'sr_support_strength',
                'sr_resistance_upper', 'sr_resistance_lower', 'sr_resistance_strength']:
        if col in df.columns:
            val = _safe_json(row[col])
            if val is not None:
                sr_data[col.replace('sr_', '')] = val
    if row.get('sr_active') and sr_data:
        context['active_zones']['sr'] = sr_data
