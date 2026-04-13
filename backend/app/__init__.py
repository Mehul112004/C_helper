import os
import atexit
from flask import Flask
from flask_cors import CORS
from sqlalchemy import text
from app.models.db import db
from app.blueprints.data import data_bp
from app.blueprints.indicators_bp import indicators_bp
from app.blueprints.sr_zones_bp import sr_zones_bp
from app.blueprints.strategies_bp import strategies_bp
from app.blueprints.signals_bp import signals_bp
from app.blueprints.backtest_bp import backtest_bp

def create_app(test_config=None):
    app = Flask(__name__)
    CORS(app)
    
    # Configure Database
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/signals_db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Apply test overrides
    if test_config:
        app.config.update(test_config)

    db.init_app(app)

    # Register blueprints
    app.register_blueprint(data_bp, url_prefix='/api/data')
    app.register_blueprint(indicators_bp, url_prefix='/api/indicators')
    app.register_blueprint(sr_zones_bp, url_prefix='/api/sr-zones')
    app.register_blueprint(strategies_bp, url_prefix='/api/strategies')
    app.register_blueprint(signals_bp, url_prefix='/api/signals')
    app.register_blueprint(backtest_bp, url_prefix='/api/backtest')

    with app.app_context():
        # Create tables
        db.create_all()
        # Create hypertable if it doesn't exist
        try:
            db.session.execute(text("SELECT create_hypertable('candles', 'open_time', if_not_exists => TRUE);"))
            db.session.commit()
        except Exception as e:
            # Table might already be a hypertable, rollback session to be safe
            db.session.rollback()
            print(f"Hypertable initialization info: {e}")

        # Initialize strategy registry
        from app.core.strategy_loader import registry
        registry.load_builtin_strategies()
        registry.sync_with_db()

    # Initialize background scheduler and live scanner (only in non-testing mode)
    if not app.config.get('TESTING', False):
        from app.core.scheduler import init_scheduler
        init_scheduler(app)

        from app.core.scanner import live_scanner
        live_scanner.set_app(app)
        atexit.register(live_scanner.stop_all)
        
        from app.core.llm_queue import llm_queue
        llm_queue.set_app(app)
        llm_queue.start()
        atexit.register(llm_queue.stop)
        
        from app.core.telegram_queue import telegram_queue
        telegram_queue.set_app(app)
        telegram_queue.start()
        atexit.register(telegram_queue.stop)
        
        from app.core.outcome_tracker import outcome_tracker
        outcome_tracker.set_app(app)
        outcome_tracker.rebuild_cache()

    return app
