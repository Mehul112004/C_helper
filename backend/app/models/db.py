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


class WatchingSetup(db.Model):
    """
    Tracks detected trade setups that are being monitored (watching cards).
    Created when a strategy fires a SetupSignal, updated on re-fire (dedup),
    expired after N candle closes without re-confirmation.
    """
    __tablename__ = 'watching_setups'

    id = db.Column(db.String(36), primary_key=True)                       # UUID
    session_id = db.Column(db.String(36), nullable=False, index=True)     # Analysis session
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    direction = db.Column(db.String(10), nullable=False)                  # LONG / SHORT
    strategy_name = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    entry = db.Column(db.Float)
    sl = db.Column(db.Float)
    tp1 = db.Column(db.Float)
    tp2 = db.Column(db.Float)
    notes = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='WATCHING')                 # WATCHING / EXPIRED / CONFIRMED / REJECTED
    candles_since_detected = db.Column(db.Integer, default=0)
    expiry_candles = db.Column(db.Integer, default=3)                     # Configurable via env
    detected_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    expired_at = db.Column(db.DateTime(timezone=True), nullable=True)
    zone_description = db.Column(db.Text, default='')                    # e.g. "Resistance at $3,420"
    condition_description = db.Column(db.Text, default='')               # e.g. "Bearish engulfing on 1h close"
    telegram_message_id = db.Column(db.String(50), nullable=True)        # Used to reply with verdicts

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'strategy_name': self.strategy_name,
            'confidence': self.confidence,
            'entry': self.entry,
            'sl': self.sl,
            'tp1': self.tp1,
            'tp2': self.tp2,
            'notes': self.notes,
            'status': self.status,
            'candles_since_detected': self.candles_since_detected,
            'expiry_candles': self.expiry_candles,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'expired_at': self.expired_at.isoformat() if self.expired_at else None,
            'zone_description': self.zone_description,
            'condition_description': self.condition_description,
        }


class AnalysisSessionRecord(db.Model):
    """
    Lightweight DB record of an analysis session.
    Sessions are ephemeral (in-memory), but persisted here
    for SSE stream reference and watching setup foreign key context.
    """
    __tablename__ = 'analysis_sessions'

    id = db.Column(db.String(36), primary_key=True)                       # UUID
    symbol = db.Column(db.String(50), nullable=False)
    strategy_names = db.Column(db.Text, nullable=False)                   # JSON array
    timeframes = db.Column(db.Text, nullable=False)                       # JSON array
    status = db.Column(db.String(20), default='active')                   # active / stopped
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    stopped_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'symbol': self.symbol,
            'strategy_names': json.loads(self.strategy_names) if self.strategy_names else [],
            'timeframes': json.loads(self.timeframes) if self.timeframes else [],
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'stopped_at': self.stopped_at.isoformat() if self.stopped_at else None,
        }


class ConfirmedSignal(db.Model):
    """
    Final trade signals that have passed the LLM confirmation pipeline.
    Displayed on the Confirmed feed in the UI and sent to Telegram.
    """
    __tablename__ = 'confirmed_signals'

    id = db.Column(db.String(36), primary_key=True)                       # UUID
    watching_setup_id = db.Column(db.String(36), nullable=False)          # Link to origin setup
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    direction = db.Column(db.String(10), nullable=False)                  # LONG / SHORT
    strategy_name = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    
    entry = db.Column(db.Float, nullable=False)
    sl = db.Column(db.Float, nullable=False)
    tp1 = db.Column(db.Float, nullable=False)
    tp2 = db.Column(db.Float, nullable=False)
    
    verdict_status = db.Column(db.String(20), nullable=False)             # CONFIRMED / MODIFIED
    reasoning_text = db.Column(db.Text, nullable=False)
    
    trade_outcome = db.Column(db.String(20), default='ACTIVE')            # ACTIVE / HIT_TP1 / HIT_TP2 / HIT_SL / EXPIRED
    
    telegram_status = db.Column(db.String(20), default='PENDING')         # PENDING / SENT / FAILED
    telegram_retries = db.Column(db.Integer, default=0)
    telegram_message_id = db.Column(db.String(50), nullable=True)         # Useful for reply
    
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    outcome_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'watching_setup_id': self.watching_setup_id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'strategy_name': self.strategy_name,
            'confidence': self.confidence,
            'entry': self.entry,
            'sl': self.sl,
            'tp1': self.tp1,
            'tp2': self.tp2,
            'verdict_status': self.verdict_status,
            'reasoning_text': self.reasoning_text,
            'trade_outcome': self.trade_outcome,
            'telegram_status': self.telegram_status,
            'telegram_retries': self.telegram_retries,
            'telegram_message_id': self.telegram_message_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'outcome_updated_at': self.outcome_updated_at.isoformat() if self.outcome_updated_at else None,
        }


class RejectedSignal(db.Model):
    """
    Trade signals that were rejected by the LLM confirmation pipeline.
    """
    __tablename__ = 'rejected_signals'

    id = db.Column(db.String(36), primary_key=True)                       # UUID
    watching_setup_id = db.Column(db.String(36), nullable=False)          # Link to origin setup
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    direction = db.Column(db.String(10), nullable=False)                  # LONG / SHORT
    strategy_name = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    
    entry = db.Column(db.Float, nullable=True)
    sl = db.Column(db.Float, nullable=True)
    tp1 = db.Column(db.Float, nullable=True)
    tp2 = db.Column(db.Float, nullable=True)
    
    reasoning_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    def to_dict(self):
        return {
            'id': self.id,
            'watching_setup_id': self.watching_setup_id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'strategy_name': self.strategy_name,
            'confidence': self.confidence,
            'entry': self.entry,
            'sl': self.sl,
            'tp1': self.tp1,
            'tp2': self.tp2,
            'reasoning_text': self.reasoning_text,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class BacktestRun(db.Model):
    """
    Stores the configuration and summary metrics for each backtest execution.
    Equity curve is stored as a JSON array of {time, value} dicts.
    """
    __tablename__ = 'backtest_runs'

    id = db.Column(db.String(36), primary_key=True)
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    strategy_names = db.Column(db.Text, nullable=False)          # JSON array
    start_date = db.Column(db.DateTime(timezone=True), nullable=False)
    end_date = db.Column(db.DateTime(timezone=True), nullable=False)
    initial_capital = db.Column(db.Float, nullable=False)
    risk_per_trade = db.Column(db.Float, nullable=False)         # fraction, e.g. 0.01

    # Summary metrics (populated after run completes)
    total_trades = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float)
    total_pnl = db.Column(db.Float)
    total_pnl_pct = db.Column(db.Float)
    sharpe_ratio = db.Column(db.Float)
    sortino_ratio = db.Column(db.Float)
    max_drawdown = db.Column(db.Float)
    max_drawdown_pct = db.Column(db.Float)
    avg_rr = db.Column(db.Float)
    profit_factor = db.Column(db.Float)
    avg_trade_duration_mins = db.Column(db.Float)
    best_trade_pnl = db.Column(db.Float)
    worst_trade_pnl = db.Column(db.Float)

    status = db.Column(db.String(20), default='RUNNING')         # RUNNING / COMPLETED / FAILED
    error_message = db.Column(db.Text, nullable=True)
    equity_curve = db.Column(db.Text, nullable=True)             # JSON array of {time, value}

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    trades = db.relationship('BacktestTrade', backref='run', lazy='dynamic',
                             cascade='all, delete-orphan')

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'strategy_names': json.loads(self.strategy_names) if self.strategy_names else [],
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'initial_capital': self.initial_capital,
            'risk_per_trade': self.risk_per_trade,
            'total_trades': self.total_trades,
            'win_rate': self.win_rate,
            'total_pnl': self.total_pnl,
            'total_pnl_pct': self.total_pnl_pct,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'avg_rr': self.avg_rr,
            'profit_factor': self.profit_factor,
            'avg_trade_duration_mins': self.avg_trade_duration_mins,
            'best_trade_pnl': self.best_trade_pnl,
            'worst_trade_pnl': self.worst_trade_pnl,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class BacktestTrade(db.Model):
    """
    Individual trade records for a backtest run.
    Each trade has entry/exit prices, SL/TP levels, outcome, PnL, and duration.
    """
    __tablename__ = 'backtest_trades'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(db.String(36), db.ForeignKey('backtest_runs.id'), nullable=False, index=True)

    trade_number = db.Column(db.Integer, nullable=False)
    entry_time = db.Column(db.DateTime(timezone=True), nullable=False)
    exit_time = db.Column(db.DateTime(timezone=True))
    symbol = db.Column(db.String(50), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    direction = db.Column(db.String(10), nullable=False)         # LONG / SHORT
    strategy_name = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float)

    entry_price = db.Column(db.Float, nullable=False)
    sl_price = db.Column(db.Float, nullable=False)
    tp1_price = db.Column(db.Float, nullable=False)
    tp2_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float)

    outcome = db.Column(db.String(20))                           # HIT_TP1 / HIT_TP2 / HIT_SL / EXPIRED
    pnl = db.Column(db.Float)
    pnl_pct = db.Column(db.Float)
    rr_ratio = db.Column(db.Float)
    duration_mins = db.Column(db.Float)
    notes = db.Column(db.Text, default='')

    def to_dict(self):
        return {
            'trade_number': self.trade_number,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'strategy_name': self.strategy_name,
            'confidence': self.confidence,
            'entry_price': self.entry_price,
            'sl_price': self.sl_price,
            'tp1_price': self.tp1_price,
            'tp2_price': self.tp2_price,
            'exit_price': self.exit_price,
            'outcome': self.outcome,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'rr_ratio': self.rr_ratio,
            'duration_mins': self.duration_mins,
            'notes': self.notes,
        }

class LLMPromptLog(db.Model):
    """
    Logs every interaction with the LLM. 
    Loose coupling referencing 'watching_setup_id' since setups can be deleted.
    """
    __tablename__ = 'llm_prompt_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    watching_setup_id = db.Column(db.String(100), index=True) # Loose reference
    symbol = db.Column(db.String(20), nullable=False)
    strategy_name = db.Column(db.String(50), nullable=False)
    model_name = db.Column(db.String(100)) # e.g. google/gemma-4-e4b
    prompt_text = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=True)
    parsed_verdict = db.Column(db.String(20)) # CONFIRM, REJECT, MODIFY, ERROR
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    def to_dict(self):
        return {
            'id': self.id,
            'watching_setup_id': self.watching_setup_id,
            'symbol': self.symbol,
            'strategy_name': self.strategy_name,
            'model_name': self.model_name,
            'prompt_text': self.prompt_text,
            'response_text': self.response_text,
            'parsed_verdict': self.parsed_verdict,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
