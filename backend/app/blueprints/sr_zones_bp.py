"""
S/R Zones API Blueprint
Endpoints:
  GET  /api/sr-zones           — Fetch stored S/R zones with optional filters
  POST /api/sr-zones/refresh   — Manually trigger a full zone refresh for a symbol
"""

from flask import Blueprint, request, jsonify
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
        timeframe (optional): Filter by origin timeframe (e.g. '4h', '1D')
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

    timeframes = ['4h', '1D']
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
