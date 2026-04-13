from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Candle(db.Model):
    __tablename__ = 'candles'

    # TimescaleDB hypertables work best without a standard auto-increment PK.
    # We use a composite primary key consisting of symbol, timeframe, and open_time.
    symbol = db.Column(db.String(50), primary_key=True)
    timeframe = db.Column(db.String(10), primary_key=True)
    open_time = db.Column(db.DateTime(timezone=True), primary_key=True)
    
    open = db.Column(db.Float, nullable=False)
    high = db.Column(db.Float, nullable=False)
    low = db.Column(db.Float, nullable=False)
    close = db.Column(db.Float, nullable=False)
    volume = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'open_time': self.open_time.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume
        }


class SRZone(db.Model):
    __tablename__ = 'sr_zones'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    symbol = db.Column(db.String(50), nullable=False, index=True)
    timeframe = db.Column(db.String(10), nullable=False)           # origin timeframe
    price_level = db.Column(db.Float, nullable=False)              # center of zone
    zone_upper = db.Column(db.Float, nullable=False)               # upper bound
    zone_lower = db.Column(db.Float, nullable=False)               # lower bound
    zone_type = db.Column(db.String(20), nullable=False)           # 'support', 'resistance', 'both'
    detection_method = db.Column(db.String(50), nullable=False)    # 'swing', 'round_number', 'prev_day_hl', 'prev_week_hl'
    strength_score = db.Column(db.Float, default=0.0)              # 0.0–1.0, based on touches + tf weight
    touch_count = db.Column(db.Integer, default=0)                 # how many times price respected this level
    last_tested = db.Column(db.DateTime(timezone=True))            # when price last touched the zone
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())

    # Unique constraint: one zone per symbol+timeframe+price_level+method
    __table_args__ = (
        db.UniqueConstraint('symbol', 'timeframe', 'price_level', 'detection_method', name='uq_sr_zone'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'price_level': self.price_level,
            'zone_upper': self.zone_upper,
            'zone_lower': self.zone_lower,
            'zone_type': self.zone_type,
            'detection_method': self.detection_method,
            'strength_score': self.strength_score,
            'touch_count': self.touch_count,
            'last_tested': self.last_tested.isoformat() if self.last_tested else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Strategy(db.Model):
    __tablename__ = 'strategies'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), unique=True, nullable=False)           # "EMA Crossover"
    description = db.Column(db.Text, default='')
    strategy_type = db.Column(db.String(20), nullable=False)                # 'builtin' or 'custom'
    timeframes = db.Column(db.Text, nullable=False)                         # JSON array: '["1h", "4h"]'
    enabled = db.Column(db.Boolean, default=True)
    min_confidence = db.Column(db.Float, default=0.5)                       # configurable threshold
    code = db.Column(db.Text, nullable=True)                                # Python source (custom only)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'strategy_type': self.strategy_type,
            'timeframes': json.loads(self.timeframes) if self.timeframes else [],
            'enabled': self.enabled,
            'min_confidence': self.min_confidence,
            'has_code': self.code is not None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
