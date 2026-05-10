"""
S/R Zones API Blueprint
Endpoints:
  GET  /api/sr-zones           — Fetch stored S/R zones with optional filters
  POST /api/sr-zones/refresh   — Manually trigger a full zone refresh for a symbol
  GET  /api/smc-zones          — Compute FVG/OB zones from candle data on-the-fly
"""

from flask import Blueprint, request, jsonify
import pandas as pd
from app.models.db import db, SRZone
from app.core.sr_engine import SREngine
from app.core.config import SUPPORTED_SYMBOLS

sr_zones_bp = Blueprint('sr_zones', __name__)


@sr_zones_bp.route('', methods=['GET'])
def get_sr_zones():
    """
    Get stored S/R zones for a given symbol.

    Query params:
        symbol (required): Trading pair, e.g. 'BTCUSDT'
        timeframe (optional): Filter by origin timeframe (e.g. '4h', '1d')
        min_strength (optional): Minimum strength score to include (0.0–1.0, default 0.0)
        near_price (optional): Only return zones within ±3% of this price

    Returns:
        JSON with list of zones and metadata.
    """
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({'error': 'Missing required query parameter: symbol'}), 400

    timeframe = request.args.get('timeframe')
    min_strength = request.args.get('min_strength', 0.0, type=float)
    near_price = request.args.get('near_price', type=float)

    try:
        query = SRZone.query.filter_by(symbol=symbol)

        if timeframe:
            query = query.filter_by(timeframe=timeframe)

        if min_strength > 0:
            query = query.filter(SRZone.strength_score >= min_strength)

        if near_price:
            # Filter zones within ±3% of the given price
            price_lower = near_price * 0.97
            price_upper = near_price * 1.03
            query = query.filter(
                SRZone.price_level >= price_lower,
                SRZone.price_level <= price_upper
            )

        # Order by strength descending (strongest zones first)
        zones = query.order_by(SRZone.strength_score.desc()).all()

        # Determine last refresh time
        last_refreshed = None
        if zones:
            most_recent = max(z.updated_at for z in zones if z.updated_at)
            last_refreshed = most_recent.isoformat() if most_recent else None

        return jsonify({
            'symbol': symbol,
            'zones': [z.to_dict() for z in zones],
            'count': len(zones),
            'last_refreshed': last_refreshed,
            'filters': {
                'timeframe': timeframe,
                'min_strength': min_strength,
                'near_price': near_price,
            }
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@sr_zones_bp.route('/refresh', methods=['POST'])
def refresh_zones():
    """
    Manually trigger a full S/R zone refresh.
    Useful for initial zone computation after importing data, or for testing.

    Body (JSON):
        symbol (required): Trading pair to refresh. Use 'all' for all supported symbols.
        timeframe (optional): Specific timeframe. Default: refreshes all [4h, 1D].
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol')

    if not symbol:
        return jsonify({'error': 'Missing required field: symbol'}), 400

    timeframes = ['4h', '1d']
    target_timeframe = body.get('timeframe')
    if target_timeframe:
        timeframes = [target_timeframe]

    symbols = SUPPORTED_SYMBOLS if symbol == 'all' else [symbol]

    try:
        total_zones = 0
        results = []

        for sym in symbols:
            for tf in timeframes:
                zones = SREngine.detect_zones(sym, tf)
                if zones:
                    SREngine.persist_zones(sym, tf, zones)
                    total_zones += len(zones)
                results.append({
                    'symbol': sym,
                    'timeframe': tf,
                    'zones_detected': len(zones) if zones else 0,
                })

        return jsonify({
            'message': f'Zone refresh complete. {total_zones} zones persisted.',
            'results': results,
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@sr_zones_bp.route('/smc-zones', methods=['GET'])
def get_smc_zones():
    """
    Compute Fair Value Gaps (FVGs) and Order Blocks (OBs) on-the-fly
    from candle data. Zones are NOT persisted — computed in-memory per request.

    Query params:
        symbol (required): Trading pair, e.g. 'BTCUSDT'
        timeframe (required): Candle timeframe (e.g. '1h', '4h')
        limit (optional): How many candles to scan (default 200)

    Returns:
        JSON with list of active FVG and OB zones.
    """
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({'error': 'Missing required query parameter: symbol'}), 400

    timeframe = request.args.get('timeframe', '1h')
    limit = request.args.get('limit', 200, type=int)

    try:
        from app.core.data_utils import get_finalized_candles
        from app.core.market_structure import extract_fvgs, extract_order_blocks
        from app.core.events import detect_choch, detect_liquidity_sweep

        df = get_finalized_candles(symbol, timeframe, limit=limit)

        if len(df) == 0:
            return jsonify({'symbol': symbol, 'timeframe': timeframe, 'zones': [], 'count': 0}), 200

        df = extract_fvgs(df)
        df = extract_order_blocks(df)
        df = detect_choch(df)
        df = detect_liquidity_sweep(df)

        import numpy as np
        zones = []

        # ── Active FVGs ──
        active_fvg_rows = df[df['fvg_active'] == True]
        for _, row in active_fvg_rows.iterrows():
            upper = float(row['fvg_upper']) if not pd.isna(row.get('fvg_upper')) else None
            lower = float(row['fvg_lower']) if not pd.isna(row.get('fvg_lower')) else None
            if upper is None or lower is None:
                continue
            direction = 'bullish' if upper > lower else 'bearish'
            zones.append({
                'type': 'fvg',
                'direction': direction,
                'upper': upper,
                'lower': lower,
                'volume': float(row['fvg_volume']) if not pd.isna(row.get('fvg_volume')) else None,
                'created_at': str(row['fvg_created_at']) if not pd.isna(row.get('fvg_created_at')) else None,
                'active': True,
            })

        # ── Active OBs ──
        active_ob_rows = df[df['ob_active'] == True]
        for _, row in active_ob_rows.iterrows():
            upper = float(row['ob_upper']) if not pd.isna(row.get('ob_upper')) else None
            lower = float(row['ob_lower']) if not pd.isna(row.get('ob_lower')) else None
            if upper is None or lower is None:
                continue
            zones.append({
                'type': 'ob',
                'direction': str(row.get('ob_direction', 'bullish')),
                'upper': upper,
                'lower': lower,
                'volume': float(row['ob_volume']) if not pd.isna(row.get('ob_volume')) else None,
                'created_at': str(row['ob_created_at']) if not pd.isna(row.get('ob_created_at')) else None,
                'active': True,
            })

        # ── Recent ChoCh/BOS events ──
        for col, label in [('event_choch_bullish_recent', 'ChoCh Bullish'),
                            ('event_choch_bearish_recent', 'ChoCh Bearish'),
                            ('event_bos_bullish_recent', 'BOS Bullish'),
                            ('event_bos_bearish_recent', 'BOS Bearish')]:
            if col in df.columns and df.iloc[-1].get(col, False):
                zones.append({
                    'type': 'event',
                    'label': label,
                    'active': True,
                })

        return jsonify({
            'symbol': symbol,
            'timeframe': timeframe,
            'zones': zones,
            'count': len(zones),
            'candles_scanned': len(df),
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
