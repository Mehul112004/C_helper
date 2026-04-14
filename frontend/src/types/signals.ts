// Phase 4: TypeScript interfaces for live analysis sessions, watching setups, and SSE events

export interface AnalysisSession {
  session_id: string;
  symbol: string;
  strategy_names: string[];
  timeframes: string[];
  status: 'active' | 'stopping' | 'stopped';
  created_at: string;
  live_price: number | null;
  live_price_updated_at: string | null;
}

export interface WatchingSetup {
  id: string;
  session_id: string;
  symbol: string;
  timeframe: string;
  direction: 'LONG' | 'SHORT';
  strategy_name: string;
  confidence: number;
  entry: number | null;
  sl: number | null;
  tp1: number | null;
  tp2: number | null;
  notes: string;
  status: 'WATCHING' | 'EXPIRED' | 'CONFIRMED' | 'REJECTED';
  candles_since_detected: number;
  expiry_candles: number;
  detected_at: string;
  zone_description: string;
  condition_description: string;
}

export interface ConfirmedSignal {
  id: string;
  watching_setup_id: string;
  session_id: string; // Joined dynamically on the backend
  symbol: string;
  timeframe: string;
  direction: 'LONG' | 'SHORT';
  strategy_name: string;
  confidence: number;
  entry: number;
  sl: number;
  tp1: number;
  tp2: number;
  verdict_status: 'CONFIRMED' | 'MODIFIED' | 'REJECTED';
  reasoning_text: string;
  trade_outcome: 'ACTIVE' | 'HIT_TP1' | 'HIT_TP2' | 'HIT_SL' | 'EXPIRED';
  telegram_status: 'PENDING' | 'SENT' | 'FAILED';
  telegram_message_id: string | null;
  created_at: string;
  outcome_updated_at: string | null;
}

export interface PriceUpdate {
  session_id: string;
  symbol: string;
  price: number;
  timestamp: string;
}

export interface CandleCloseEvent {
  symbol: string;
  timeframe: string;
  close: number;
  timestamp: string;
}

export type SSEEventType =
  | 'setup_detected'
  | 'setup_expired'
  | 'setup_updated'
  | 'session_started'
  | 'session_stopped'
  | 'candle_close'
  | 'price_update'
  | 'signal_confirmed';

export interface SSEEvent {
  type: SSEEventType;
  data: AnalysisSession | WatchingSetup | ConfirmedSignal | PriceUpdate | CandleCloseEvent | Record<string, unknown>;
}

export interface Strategy {
  id: number;
  name: string;
  description: string;
  strategy_type: string;
  timeframes: string[];
  enabled: boolean;
  min_confidence: number;
}
