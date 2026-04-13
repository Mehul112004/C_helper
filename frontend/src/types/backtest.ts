// Phase 7: TypeScript interfaces for backtesting

export interface BacktestConfig {
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  strategy_names: string[];
  initial_capital: number;
  risk_per_trade: number; // percentage, e.g. 1.0 = 1%
}

export interface BacktestMetrics {
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  total_pnl_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  avg_rr: number;
  profit_factor: number;
  avg_trade_duration_mins: number;
  best_trade_pnl: number;
  worst_trade_pnl: number;
}

export interface BacktestTrade {
  trade_number: number;
  entry_time: string;
  exit_time: string | null;
  symbol: string;
  timeframe: string;
  direction: 'LONG' | 'SHORT';
  strategy_name: string;
  confidence: number;
  entry_price: number;
  sl_price: number;
  tp1_price: number;
  tp2_price: number;
  exit_price: number | null;
  outcome: 'HIT_TP1' | 'HIT_TP2' | 'HIT_SL' | 'EXPIRED' | null;
  pnl: number | null;
  pnl_pct: number | null;
  rr_ratio: number | null;
  duration_mins: number | null;
  notes: string;
}

export interface EquityCurvePoint {
  time: string;
  value: number;
}

export interface BacktestResult {
  run_id: string;
  status: 'COMPLETED' | 'FAILED';
  metrics: BacktestMetrics;
  equity_curve: EquityCurvePoint[];
  trades: BacktestTrade[];
  trade_count: number;
  candle_count: number;
  error?: string;
}

export interface BacktestRunSummary {
  id: string;
  symbol: string;
  timeframe: string;
  strategy_names: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  risk_per_trade: number;
  total_trades: number;
  win_rate: number | null;
  total_pnl: number | null;
  status: string;
  created_at: string;
}
