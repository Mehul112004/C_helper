from flask import Blueprint, request, jsonify
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func
from app.models.db import db, Candle
from app.utils.binance import fetch_klines
from app.utils.csv_parser import parse_binance_csv
from datetime import datetime

data_bp = Blueprint('data', __name__)

@data_bp.route('/import/binance', methods=['POST'])
def import_binance():
    body = request.json
    required_fields = ['symbol', 'timeframe', 'start_time', 'end_time']
    if not all(k in body for k in required_fields):
        return jsonify({"error": f"Missing fields. Required: {required_fields}"}), 400

    symbol = body['symbol']
    timeframe = body['timeframe']
    
    try:
        # Convert iso format to ms timestamp if needed
        # Assuming frontend passes ms timestamps directly, or we handle ISO strings here
        start_ts = body['start_time']
        end_ts = body['end_time']
        
        if isinstance(start_ts, str):
            start_ts = int(datetime.fromisoformat(start_ts.replace('Z', '+00:00')).timestamp() * 1000)
        if isinstance(end_ts, str):
            end_ts = int(datetime.fromisoformat(end_ts.replace('Z', '+00:00')).timestamp() * 1000)

        candles = fetch_klines(symbol, timeframe, start_ts, end_ts)

        if not candles:
            return jsonify({"message": "No data returned from Binance for this timeframe"}), 200

        # Bulk upsert using SQLAlchemy PostgreSQL dialect
        stmt = insert(Candle).values(candles)
        do_upsert = stmt.on_conflict_do_update(
            index_elements=['symbol', 'timeframe', 'open_time'],
            set_={
                'open': stmt.excluded.open,
                'high': stmt.excluded.high,
                'low': stmt.excluded.low,
                'close': stmt.excluded.close,
                'volume': stmt.excluded.volume
            }
        )
        db.session.execute(do_upsert)
        db.session.commit()

        return jsonify({"message": "Success", "count": len(candles)}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@data_bp.route('/import/csv', methods=['POST'])
def import_csv():
    # check if the post request has the file part
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    symbol = request.form.get('symbol')
    timeframe = request.form.get('timeframe')

    if not symbol or not timeframe:
        return jsonify({"error": "Missing symbol or timeframe"}), 400

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        candles = parse_binance_csv(file, symbol, timeframe)
        if not candles:
             return jsonify({"error": "No valid data parsed."}), 400
             
        stmt = insert(Candle).values(candles)
        do_upsert = stmt.on_conflict_do_update(
            index_elements=['symbol', 'timeframe', 'open_time'],
            set_={
                'open': stmt.excluded.open,
                'high': stmt.excluded.high,
                'low': stmt.excluded.low,
                'close': stmt.excluded.close,
                'volume': stmt.excluded.volume
            }
        )
        db.session.execute(do_upsert)
        db.session.commit()

        return jsonify({"message": "Success", "count": len(candles)}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@data_bp.route('/datasets', methods=['GET'])
def get_datasets():
    try:
        # SELECT symbol, timeframe, MIN(open_time), MAX(open_time), COUNT(*) FROM candles GROUP BY symbol, timeframe
        results = db.session.query(
            Candle.symbol,
            Candle.timeframe,
            func.min(Candle.open_time).label('start_time'),
            func.max(Candle.open_time).label('end_time'),
            func.count(Candle.open_time).label('count')
        ).group_by(Candle.symbol, Candle.timeframe).all()

        datasets = []
        for row in results:
            datasets.append({
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "start_time": row.start_time.isoformat() if row.start_time else None,
                "end_time": row.end_time.isoformat() if row.end_time else None,
                "count": row.count,
                "source": "Local Db" # Could dynamically query specific properties if tracked later
            })

        return jsonify({"datasets": datasets}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
