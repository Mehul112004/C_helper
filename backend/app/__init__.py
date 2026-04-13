import os
from flask import Flask
from flask_cors import CORS
from sqlalchemy import text
from app.models.db import db
from app.blueprints.data import data_bp
from app.blueprints.indicators_bp import indicators_bp
from app.blueprints.sr_zones_bp import sr_zones_bp
from app.blueprints.strategies_bp import strategies_bp

def create_app():
    app = Flask(__name__)
    CORS(app)
    
    # Configure Database
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/signals_db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    # Register blueprints
    app.register_blueprint(data_bp, url_prefix='/api/data')
    app.register_blueprint(indicators_bp, url_prefix='/api/indicators')
    app.register_blueprint(sr_zones_bp, url_prefix='/api/sr-zones')
    app.register_blueprint(strategies_bp, url_prefix='/api/strategies')

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

    # Initialize background scheduler (only in non-testing mode)
    if not app.config.get('TESTING', False):
        from app.core.scheduler import init_scheduler
        init_scheduler(app)

    return app

