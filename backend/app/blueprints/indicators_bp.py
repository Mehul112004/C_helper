"""
Indicators API Blueprint
Endpoint: GET /api/indicators?symbol=BTCUSDT&timeframe=4h&include_series=false
Serves pre-calculated technical indicator data.
"""

from flask import Blueprint, request, jsonify
from app.core.indicators import IndicatorService

indicators_bp = Blueprint('indicators', __name__)


@indicators_bp.route('', methods=['GET'])
def get_indicators():
    """
    Get technical indicators for a given symbol and timeframe.

    Query params:
        symbol (required): Trading pair, e.g. 'BTCUSDT'
        timeframe (required): Candle timeframe, e.g. '1h', '4h', '1d'
        include_series (optional): If 'true', includes full indicator series for charting.
                                   Default: 'false' (returns only latest values).

    Returns:
        JSON with 'latest' values, optional 'series' arrays, 'warnings', and metadata.
    """
    symbol = request.args.get('symbol')
    timeframe = request.args.get('timeframe')
    include_series = request.args.get('include_series', 'false').lower() == 'true'

    if not symbol or not timeframe:
        return jsonify({
            'error': 'Missing required query parameters: symbol, timeframe'
        }), 400

    # Validate timeframe
    valid_timeframes = ['5m', '15m', '1h', '4h', '1d']
    if timeframe not in valid_timeframes:
        return jsonify({
            'error': f'Invalid timeframe: {timeframe}. Valid: {valid_timeframes}'
        }), 400

    try:
        result = IndicatorService.compute_all(symbol, timeframe, include_series=include_series)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@indicators_bp.route('/invalidate', methods=['POST'])
def invalidate_cache():
    """
    Manually invalidate the indicator cache for a symbol/timeframe.
    Useful after importing new data or for debugging.

    Body (JSON, optional):
        symbol: Specific symbol to invalidate (omit to clear all)
        timeframe: Specific timeframe to invalidate (omit to clear all)
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol')
    timeframe = body.get('timeframe')

    IndicatorService.invalidate_cache(symbol, timeframe)

    return jsonify({
        'message': 'Cache invalidated',
        'symbol': symbol or 'all',
        'timeframe': timeframe or 'all',
    }), 200
