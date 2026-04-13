"""
Strategies API Blueprint
Endpoints:
  GET    /api/strategies              — List all registered strategies
  GET    /api/strategies/<name>       — Get details for a single strategy
  POST   /api/strategies/<name>/toggle — Enable or disable a strategy
  POST   /api/strategies/<name>/confidence — Update min confidence threshold
"""

from flask import Blueprint, request, jsonify

strategies_bp = Blueprint('strategies', __name__)


@strategies_bp.route('', methods=['GET'])
def list_strategies():
    """
    List all registered strategies with their current enabled state and metadata.

    Returns:
        JSON with list of strategy objects and count.
    """
    from app.core.strategy_loader import registry
    strategies = registry.get_all()
    return jsonify({'strategies': strategies, 'count': len(strategies)}), 200


@strategies_bp.route('/<name>', methods=['GET'])
def get_strategy(name):
    """
    Get full details for a single strategy.

    Args:
        name: Strategy name (URL-encoded if it contains spaces)

    Returns:
        JSON with strategy details or 404 if not found.
    """
    from app.core.strategy_loader import registry
    strategy = registry.get_by_name(name)
    if not strategy:
        return jsonify({'error': f'Strategy not found: {name}'}), 404

    return jsonify({
        'name': strategy.name,
        'description': strategy.description,
        'timeframes': strategy.timeframes,
        'version': strategy.version,
        'enabled': registry.is_enabled(name),
        'min_confidence': strategy.min_confidence,
    }), 200


@strategies_bp.route('/<name>/toggle', methods=['POST'])
def toggle_strategy(name):
    """
    Enable or disable a strategy.

    Body (JSON):
        enabled (required): true or false

    Returns:
        JSON confirmation or error.
    """
    body = request.get_json(silent=True) or {}
    enabled = body.get('enabled')

    if enabled is None:
        return jsonify({'error': 'Missing required field: enabled'}), 400

    from app.core.strategy_loader import registry
    success = registry.set_enabled(name, bool(enabled))
    if not success:
        return jsonify({'error': f'Strategy not found: {name}'}), 404

    return jsonify({
        'message': f"Strategy '{name}' {'enabled' if enabled else 'disabled'}",
        'name': name,
        'enabled': bool(enabled),
    }), 200


@strategies_bp.route('/<name>/confidence', methods=['POST'])
def update_confidence(name):
    """
    Update the minimum confidence threshold for a strategy.

    Body (JSON):
        min_confidence (required): float between 0.0 and 1.0

    Returns:
        JSON confirmation or error.
    """
    body = request.get_json(silent=True) or {}
    min_confidence = body.get('min_confidence')

    if min_confidence is None:
        return jsonify({'error': 'Missing required field: min_confidence'}), 400

    try:
        min_confidence = float(min_confidence)
    except (ValueError, TypeError):
        return jsonify({'error': 'min_confidence must be a number between 0.0 and 1.0'}), 400

    if not 0.0 <= min_confidence <= 1.0:
        return jsonify({'error': 'min_confidence must be between 0.0 and 1.0'}), 400

    from app.core.strategy_loader import registry
    success = registry.set_min_confidence(name, min_confidence)
    if not success:
        return jsonify({'error': f'Strategy not found: {name}'}), 404

    return jsonify({
        'message': f"Strategy '{name}' min_confidence updated to {min_confidence}",
        'name': name,
        'min_confidence': min_confidence,
    }), 200
