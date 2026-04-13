import { useState, useEffect } from 'react';
import type { BacktestConfig, BacktestResult } from '../../types/backtest';
import type { StrategyInfo } from '../../api/client';
import { runBacktest, fetchStrategies } from '../../api/client';
import ConfigPanel from './ConfigPanel';
import MetricsSummary from './MetricsSummary';
import EquityCurve from './EquityCurve';
import TradeChart from './TradeChart';
import TradeLog from './TradeLog';

type ResultTab = 'metrics' | 'equity' | 'chart' | 'trades';

export default function Backtest() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ResultTab>('metrics');

  useEffect(() => {
    fetchStrategies().then(setStrategies).catch(console.error);
  }, []);

  const handleRunBacktest = async (config: BacktestConfig) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await runBacktest(config);
      if (data.status === 'FAILED') {
        setError((data as unknown as { error?: string }).error || 'Backtest failed');
      } else {
        setResult(data);
        setActiveTab('metrics');
      }
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } }; message?: string };
      setError(axiosErr.response?.data?.error || axiosErr.message || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  const tabs: { key: ResultTab; label: string }[] = [
    { key: 'metrics', label: 'Summary' },
    { key: 'equity', label: 'Equity Curve' },
    { key: 'chart', label: 'Trade Chart' },
    { key: 'trades', label: 'Trade Log' },
  ];

  return (
    <div className="h-full flex flex-col" id="backtest-page">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Backtest Engine</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Test strategies against historical data
          </p>
        </div>
        {result && (
          <div className="flex items-center gap-3 text-sm text-slate-400">
            <span>{result.candle_count.toLocaleString()} candles</span>
            <span className="text-slate-600">·</span>
            <span>{result.trade_count} trades</span>
          </div>
        )}
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Config Sidebar */}
        <div className="w-80 border-r border-slate-700 overflow-y-auto bg-slate-800/40 flex-shrink-0">
          <ConfigPanel
            strategies={strategies}
            onSubmit={handleRunBacktest}
            loading={loading}
          />
        </div>

        {/* Results Area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {loading && (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <div className="w-10 h-10 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin mx-auto mb-4" />
                <p className="text-slate-400">Running backtest...</p>
              </div>
            </div>
          )}

          {error && !loading && (
            <div className="flex-1 flex items-center justify-center">
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-6 py-4 max-w-md text-center">
                <p className="text-red-400 font-medium">Backtest Failed</p>
                <p className="text-red-300/70 text-sm mt-1">{error}</p>
              </div>
            </div>
          )}

          {!result && !loading && !error && (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-slate-500">
                <div className="text-5xl mb-4 opacity-30">📊</div>
                <p className="text-lg font-medium">Configure & run a backtest</p>
                <p className="text-sm mt-1">Select a symbol, strategy, and date range to begin</p>
              </div>
            </div>
          )}

          {result && !loading && (
            <>
              {/* Tab Bar */}
              <div className="px-6 pt-4 flex gap-1 border-b border-slate-700">
                {tabs.map(tab => (
                  <button
                    key={tab.key}
                    onClick={() => setActiveTab(tab.key)}
                    className={`px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors ${
                      activeTab === tab.key
                        ? 'bg-slate-700/60 text-emerald-400 border-b-2 border-emerald-400'
                        : 'text-slate-400 hover:text-white hover:bg-slate-700/30'
                    }`}
                    id={`tab-${tab.key}`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {/* Tab Content */}
              <div className="flex-1 overflow-auto p-6">
                {activeTab === 'metrics' && <MetricsSummary metrics={result.metrics} />}
                {activeTab === 'equity' && <EquityCurve data={result.equity_curve} />}
                {activeTab === 'chart' && (
                  <TradeChart
                    trades={result.trades}
                    symbol={result.trades[0]?.symbol || ''}
                    timeframe={result.trades[0]?.timeframe || ''}
                  />
                )}
                {activeTab === 'trades' && (
                  <TradeLog trades={result.trades} runId={result.run_id} />
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
