"""
Signals API Blueprint
Endpoints for analysis sessions, watching setups, and SSE streaming.

REST endpoints:
  GET    /api/signals/sessions         — List active analysis sessions
  POST   /api/signals/sessions         — Start a new analysis session
  DELETE /api/signals/sessions/<id>    — Stop an analysis session
  GET    /api/signals/watching          — Get all active watching setups
  GET    /api/signals/watching/<id>    — Get a specific watching setup
  GET    /api/signals/stream           — SSE event stream
"""

import json
import queue

from flask import Blueprint, request, jsonify, Response, stream_with_context

from app.core.sse import sse_manager

signals_bp = Blueprint('signals', __name__)


# ---------- Analysis Sessions ----------

@signals_bp.route('/sessions', methods=['GET'])
def list_sessions():
    """List all active analysis sessions."""
    from app.core.scanner import live_scanner
    sessions = live_scanner.get_active_sessions()
    return jsonify({'sessions': sessions, 'count': len(sessions)}), 200


@signals_bp.route('/sessions', methods=['POST'])
def start_session():
    """
    Start a new analysis session.

    Body (JSON):
        symbol (required): Trading pair, e.g. "BTCUSDT"
        strategy_names (required): List of strategy names to activate
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol')
    strategy_names = body.get('strategy_names', [])

    if not symbol:
        return jsonify({'error': 'Missing required field: symbol'}), 400
    if not strategy_names or not isinstance(strategy_names, list):
        return jsonify({'error': 'strategy_names must be a non-empty list'}), 400

    try:
        from app.core.scanner import live_scanner
        session = live_scanner.start_session(symbol, strategy_names)
        return jsonify({'session': session}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Failed to start session: {str(e)}'}), 500


@signals_bp.route('/sessions/<session_id>', methods=['DELETE'])
def stop_session(session_id):
    """Stop an analysis session by ID."""
    from app.core.scanner import live_scanner
    success = live_scanner.stop_session(session_id)
    if not success:
        return jsonify({'error': f'Session not found or already stopped: {session_id}'}), 404
    return jsonify({'message': f'Session {session_id} stopped'}), 200


# ---------- Watching Setups ----------

@signals_bp.route('/watching', methods=['GET'])
def list_watching():
    """
    Get all active watching setups.

    Query params:
        session_id (optional): Filter by session
    """
    from app.core.watching import WatchingManager
    session_id = request.args.get('session_id')
    setups = WatchingManager.get_active_setups(session_id)
    return jsonify({'setups': setups, 'count': len(setups)}), 200


@signals_bp.route('/watching/<setup_id>', methods=['GET'])
def get_watching(setup_id):
    """Get a specific watching setup by ID."""
    from app.core.watching import WatchingManager
    setup = WatchingManager.get_setup(setup_id)
    if not setup:
        return jsonify({'error': f'Setup not found: {setup_id}'}), 404
    return jsonify({'setup': setup}), 200


# ---------- Confirmed Signals ----------

@signals_bp.route('/confirmed', methods=['GET'])
def list_confirmed_signals():
    """
    Get all confirmed/modified signals that have passed the LLM filter.
    """
    from app.models.db import db, ConfirmedSignal
    signals = ConfirmedSignal.query.order_by(ConfirmedSignal.created_at.desc()).all()
    return jsonify({'signals': [s.to_dict() for s in signals], 'count': len(signals)}), 200

@signals_bp.route('/lm-studio-status', methods=['GET'])
def lm_studio_status():
    """
    Check if the local LM Studio instance is reachable.
    """
    from app.core.llm_client import LLMClient
    status = LLMClient.ping_status()
    return jsonify({'online': status}), 200


# ---------- Server-Sent Events ----------

@signals_bp.route('/stream')
def event_stream():
    """
    SSE endpoint — pushes real-time events to the frontend.

    Event types:
    - setup_detected: New watching card
    - setup_expired: Watching card expired
    - setup_updated: Existing watching card refreshed (dedup)
    - session_started: Analysis session started
    - session_stopped: Analysis session stopped
    - candle_close: Live candle close notification
    - price_update: Live price tick {session_id, symbol, price, timestamp}
    """
    def generate():
        q = sse_manager.subscribe()
        try:
            while True:
                try:
                    event = q.get(timeout=30)
                except queue.Empty:
                    # Send keepalive comment to prevent timeout
                    yield ": keepalive\n\n"
                    continue

                if event is None:
                    yield ": keepalive\n\n"
                else:
                    yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
        except GeneratorExit:
            sse_manager.unsubscribe(q)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )
