"""
Backtest API Blueprint
Endpoints for running backtests, fetching history, and exporting results.

Routes:
    POST /api/backtest/run      — Launch a new backtest
    GET  /api/backtest/history   — List past backtest runs
    GET  /api/backtest/<run_id>  — Fetch full results for a specific run
    GET  /api/backtest/<run_id>/export — Download trade log as CSV
"""

import json
import csv
import io
from datetime import datetime
from flask import Blueprint, request, jsonify, Response

from app.models.db import db, BacktestRun, BacktestTrade
from app.core.backtest_engine import BacktestEngine
from app.core.strategy_loader import registry

backtest_bp = Blueprint('backtest', __name__)

VALID_TIMEFRAMES = ['5m', '15m', '1h', '4h', '1D']


@backtest_bp.route('/run', methods=['POST'])
def run_backtest():
    """
    Launch a new backtest.

    Request Body:
    {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "start_date": "2025-01-01T00:00:00Z",
        "end_date": "2025-06-01T00:00:00Z",
        "strategy_names": ["EMA Crossover", "RSI Reversal"],
        "initial_capital": 10000,
        "risk_per_trade": 1.0  // percentage
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # ---------- Validate inputs ----------
    symbol = data.get('symbol', '').strip()
    if not symbol:
        return jsonify({'error': 'symbol is required'}), 400

    timeframe = data.get('timeframe', '').strip()
    if timeframe not in VALID_TIMEFRAMES:
        return jsonify({'error': f'timeframe must be one of: {", ".join(VALID_TIMEFRAMES)}'}), 400

    # Dates
    try:
        start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00'))
    except (KeyError, ValueError, TypeError):
        return jsonify({'error': 'start_date is required and must be a valid ISO datetime'}), 400

    try:
        end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00'))
    except (KeyError, ValueError, TypeError):
        return jsonify({'error': 'end_date is required and must be a valid ISO datetime'}), 400

    if start_date >= end_date:
        return jsonify({'error': 'start_date must be before end_date'}), 400

    # Strategies
    strategy_names = data.get('strategy_names', [])
    if not strategy_names or not isinstance(strategy_names, list):
        return jsonify({'error': 'strategy_names must be a non-empty array'}), 400

    strategies = []
    for name in strategy_names:
        strat = registry.get_by_name(name)
        if strat is None:
            return jsonify({'error': f'Strategy not found: {name}'}), 400
        strategies.append(strat)

    # Capital and risk
    try:
        initial_capital = float(data.get('initial_capital', 10000))
        if initial_capital <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'error': 'initial_capital must be a positive number'}), 400

    try:
        risk_per_trade = float(data.get('risk_per_trade', 1.0))
        if not (0.1 <= risk_per_trade <= 100.0):
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'error': 'risk_per_trade must be between 0.1 and 100.0'}), 400

    risk_pct = risk_per_trade / 100.0  # Convert percentage to fraction

    # ---------- Run backtest ----------
    result = BacktestEngine.run(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        strategies=strategies,
        strategy_names=strategy_names,
        initial_capital=initial_capital,
        risk_pct=risk_pct,
    )

    if result['status'] == 'FAILED':
        return jsonify({
            'run_id': result['run_id'],
            'status': 'FAILED',
            'error': result.get('error', 'Unknown error'),
        }), 422

    # Serialize datetimes in trade dicts
    serialized_trades = []
    for t in result.get('trades', []):
        trade_copy = dict(t)
        if isinstance(trade_copy.get('entry_time'), datetime):
            trade_copy['entry_time'] = trade_copy['entry_time'].isoformat()
        if isinstance(trade_copy.get('exit_time'), datetime):
            trade_copy['exit_time'] = trade_copy['exit_time'].isoformat()
        serialized_trades.append(trade_copy)

    return jsonify({
        'run_id': result['run_id'],
        'status': result['status'],
        'metrics': result['metrics'],
        'equity_curve': result['equity_curve'],
        'trades': serialized_trades,
        'trade_count': result['trade_count'],
        'candle_count': result['candle_count'],
    }), 200


@backtest_bp.route('/history', methods=['GET'])
def backtest_history():
    """List past backtest runs, most recent first."""
    runs = (
        BacktestRun.query
        .order_by(BacktestRun.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({
        'runs': [r.to_dict() for r in runs],
    }), 200


@backtest_bp.route('/<run_id>', methods=['GET'])
def get_backtest_run(run_id):
    """Fetch full results for a specific backtest run, including all trades."""
    run = BacktestRun.query.get(run_id)
    if not run:
        return jsonify({'error': 'Backtest run not found'}), 404

    trades = (
        BacktestTrade.query
        .filter_by(run_id=run_id)
        .order_by(BacktestTrade.trade_number.asc())
        .all()
    )

    # Parse equity curve from JSON
    equity_curve = []
    if run.equity_curve:
        try:
            equity_curve = json.loads(run.equity_curve)
        except (json.JSONDecodeError, TypeError):
            equity_curve = []

    return jsonify({
        'run': run.to_dict(),
        'trades': [t.to_dict() for t in trades],
        'equity_curve': equity_curve,
    }), 200


@backtest_bp.route('/<run_id>/export', methods=['GET'])
def export_backtest_csv(run_id):
    """Export the trade log for a backtest run as a downloadable CSV file."""
    run = BacktestRun.query.get(run_id)
    if not run:
        return jsonify({'error': 'Backtest run not found'}), 404

    trades = (
        BacktestTrade.query
        .filter_by(run_id=run_id)
        .order_by(BacktestTrade.trade_number.asc())
        .all()
    )

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        '#', 'Date', 'Symbol', 'Timeframe', 'Direction', 'Strategy',
        'Confidence', 'Entry', 'SL', 'TP1', 'TP2', 'Exit',
        'Outcome', 'PnL ($)', 'PnL (%)', 'R/R', 'Duration (min)', 'Notes'
    ])

    for t in trades:
        writer.writerow([
            t.trade_number,
            t.entry_time.isoformat() if t.entry_time else '',
            t.symbol,
            t.timeframe,
            t.direction,
            t.strategy_name,
            t.confidence,
            t.entry_price,
            t.sl_price,
            t.tp1_price,
            t.tp2_price,
            t.exit_price,
            t.outcome,
            t.pnl,
            t.pnl_pct,
            t.rr_ratio,
            t.duration_mins,
            t.notes or '',
        ])

    csv_content = output.getvalue()
    output.close()

    strategy_label = run.symbol + '_' + run.timeframe
    filename = f'backtest_{strategy_label}_{run_id[:8]}.csv'

    return Response(
        csv_content,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': 'text/csv',
        }
    )
