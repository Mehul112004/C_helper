import axios from 'axios';

export const apiClient = axios.create({
  baseURL: 'http://localhost:5001/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// ---------- Phase 1: Historical Data ----------

export const importBinanceData = async (payload: { symbol: string; timeframe: string; start_time: string; end_time: string }) => {
  const { data } = await apiClient.post('/data/import/binance', payload);
  return data;
};

export const importCsvData = async (formData: FormData) => {
  const { data } = await apiClient.post('/data/import/csv', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return data;
};

export const fetchDatasets = async () => {
  const { data } = await apiClient.get('/data/datasets');
  return data.datasets;
};

// ---------- Phase 2: Indicators & S/R Zones ----------

export interface IndicatorLatest {
  ema_9: number | null;
  ema_21: number | null;
  ema_50: number | null;
  ema_200: number | null;
  rsi_14: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  bb_upper: number | null;
  bb_middle: number | null;
  bb_lower: number | null;
  bb_width: number | null;
  atr_14: number | null;
  volume_ma_20: number | null;
}

export interface IndicatorSeriesPoint {
  time: string;
  value: number;
}

export interface IndicatorResponse {
  symbol: string;
  timeframe: string;
  latest: IndicatorLatest | null;
  series: Record<string, IndicatorSeriesPoint[]> | null;
  candle_count: number;
  last_updated: string | null;
  warnings: string[];
}

export interface SRZone {
  id: number;
  symbol: string;
  price_level: number;
  zone_upper: number;
  zone_lower: number;
  zone_type: 'support' | 'resistance' | 'both';
  timeframe: string;
  detection_method: string;
  strength_score: number;
  touch_count: number;
  last_tested: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SRZonesResponse {
  symbol: string;
  zones: SRZone[];
  count: number;
  last_refreshed: string | null;
}

export const fetchIndicators = async (
  symbol: string,
  timeframe: string,
  includeSeries = false
): Promise<IndicatorResponse> => {
  const { data } = await apiClient.get('/indicators', {
    params: { symbol, timeframe, include_series: includeSeries },
  });
  return data;
};

export const fetchSRZones = async (
  symbol: string,
  timeframe?: string,
  minStrength?: number,
  nearPrice?: number
): Promise<SRZonesResponse> => {
  const { data } = await apiClient.get('/sr-zones', {
    params: {
      symbol,
      timeframe,
      min_strength: minStrength,
      near_price: nearPrice,
    },
  });
  return data;
};

export const refreshSRZones = async (
  symbol: string,
  timeframe?: string
): Promise<{ message: string; results: { symbol: string; timeframe: string; zones_detected: number }[] }> => {
  const { data } = await apiClient.post('/sr-zones/refresh', { symbol, timeframe });
  return data;
};

// ---------- Phase 3: Strategies ----------

export interface StrategyInfo {
  id: number;
  name: string;
  description: string;
  strategy_type: string;
  timeframes: string[];
  enabled: boolean;
  min_confidence: number;
}

export const fetchStrategies = async (): Promise<StrategyInfo[]> => {
  const { data } = await apiClient.get('/strategies');
  return data.strategies;
};

// ---------- Phase 4: Live Analysis ----------

import type { AnalysisSession, WatchingSetup } from '../types/signals';

export const fetchActiveSessions = async (): Promise<AnalysisSession[]> => {
  const { data } = await apiClient.get('/signals/sessions');
  return data.sessions;
};

export const startSession = async (
  symbol: string,
  strategyNames: string[],
  timeframes?: string[]
): Promise<AnalysisSession> => {
  const { data } = await apiClient.post('/signals/sessions', {
    symbol,
    strategy_names: strategyNames,
    timeframes,
  });
  return data.session;
};

export const stopSession = async (sessionId: string): Promise<void> => {
  await apiClient.delete(`/signals/sessions/${sessionId}`);
};

export const fetchWatchingSetups = async (sessionId?: string): Promise<WatchingSetup[]> => {
  const { data } = await apiClient.get('/signals/watching', {
    params: sessionId ? { session_id: sessionId } : {},
  });
  return data.setups;
};

export const fetchWatchingSetup = async (setupId: string): Promise<WatchingSetup> => {
  const { data } = await apiClient.get(`/signals/watching/${setupId}`);
  return data.setup;
};

// ---------- Phase 7: Backtesting ----------

import type { BacktestConfig, BacktestResult, BacktestRunSummary } from '../types/backtest';

export const runBacktest = async (config: BacktestConfig): Promise<BacktestResult> => {
  const { data } = await apiClient.post('/backtest/run', config);
  return data;
};

export const fetchBacktestHistory = async (): Promise<BacktestRunSummary[]> => {
  const { data } = await apiClient.get('/backtest/history');
  return data.runs;
};

export const fetchBacktestRun = async (runId: string): Promise<{ run: BacktestRunSummary; trades: BacktestResult['trades']; equity_curve: BacktestResult['equity_curve'] }> => {
  const { data } = await apiClient.get(`/backtest/${runId}`);
  return data;
};

export const getBacktestExportUrl = (runId: string): string => {
  return `http://localhost:5001/api/backtest/${runId}/export`;
};
