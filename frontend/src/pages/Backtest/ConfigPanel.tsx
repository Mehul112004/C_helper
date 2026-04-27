import { useState } from 'react';
import type { BacktestConfig } from '../../types/backtest';
import type { StrategyInfo } from '../../api/client';

const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT'];
const TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d'];

interface Props {
  strategies: StrategyInfo[];
  onSubmit: (config: BacktestConfig) => void;
  loading: boolean;
}

export default function ConfigPanel({ strategies, onSubmit, loading }: Props) {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [timeframe, setTimeframe] = useState('1h');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [capital, setCapital] = useState('10000');
  const [risk, setRisk] = useState('1.0');
  const [validationError, setValidationError] = useState<string | null>(null);

  const toggleStrategy = (name: string) => {
    setSelectedStrategies(prev =>
      prev.includes(name) ? prev.filter(s => s !== name) : [...prev, name]
    );
  };

  const selectAll = () => {
    if (selectedStrategies.length === strategies.length) {
      setSelectedStrategies([]);
    } else {
      setSelectedStrategies(strategies.map(s => s.name));
    }
  };

  const handleSubmit = () => {
    setValidationError(null);

    if (!startDate || !endDate) {
      setValidationError('Start and end dates are required');
      return;
    }
    if (new Date(startDate) >= new Date(endDate)) {
      setValidationError('Start date must be before end date');
      return;
    }
    if (selectedStrategies.length === 0) {
      setValidationError('Select at least one strategy');
      return;
    }
    const capNum = parseFloat(capital);
    if (isNaN(capNum) || capNum <= 0) {
      setValidationError('Initial capital must be a positive number');
      return;
    }
    const riskNum = parseFloat(risk);
    if (isNaN(riskNum) || riskNum < 0.1 || riskNum > 100) {
      setValidationError('Risk must be between 0.1% and 100%');
      return;
    }

    onSubmit({
      symbol,
      timeframe,
      start_date: new Date(startDate).toISOString(),
      end_date: new Date(endDate).toISOString(),
      strategy_names: selectedStrategies,
      initial_capital: capNum,
      risk_per_trade: riskNum,
    });
  };

  return (
    <div className="p-5 space-y-5" id="backtest-config-panel">
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
        Configuration
      </h2>

      {/* Symbol */}
      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Symbol</label>
        <select
          value={symbol}
          onChange={e => setSymbol(e.target.value)}
          className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 outline-none"
          id="backtest-symbol-select"
        >
          {SYMBOLS.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {/* Timeframe */}
      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Timeframe</label>
        <div className="flex gap-1.5">
          {TIMEFRAMES.map(tf => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                timeframe === tf
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                  : 'bg-slate-700/50 text-slate-400 border border-slate-600 hover:text-white'
              }`}
              id={`tf-btn-${tf}`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Date Range */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Start Date</label>
          <input
            type="date"
            value={startDate}
            onChange={e => setStartDate(e.target.value)}
            className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 outline-none"
            id="backtest-start-date"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">End Date</label>
          <input
            type="date"
            value={endDate}
            onChange={e => setEndDate(e.target.value)}
            className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 outline-none"
            id="backtest-end-date"
          />
        </div>
      </div>

      {/* Strategies */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs font-medium text-slate-400">Strategies</label>
          <button
            onClick={selectAll}
            className="text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
          >
            {selectedStrategies.length === strategies.length ? 'Deselect All' : 'Select All'}
          </button>
        </div>
        <div className="space-y-1 max-h-48 overflow-y-auto rounded-lg border border-slate-600 bg-slate-700/30 p-2">
          {strategies.map(strat => (
            <label
              key={strat.name}
              className={`flex items-center gap-2.5 px-2.5 py-2 rounded-md cursor-pointer transition-colors ${
                selectedStrategies.includes(strat.name)
                  ? 'bg-emerald-500/10 border border-emerald-500/30'
                  : 'border border-transparent hover:bg-slate-700/50'
              }`}
            >
              <input
                type="checkbox"
                checked={selectedStrategies.includes(strat.name)}
                onChange={() => toggleStrategy(strat.name)}
                className="w-3.5 h-3.5 rounded border-slate-500 text-emerald-500 focus:ring-emerald-500/50 bg-slate-700"
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-white truncate">{strat.name}</div>
                <div className="text-xs text-slate-500 truncate">{strat.timeframes.join(', ')}</div>
              </div>
            </label>
          ))}
          {strategies.length === 0 && (
            <p className="text-xs text-slate-500 text-center py-4">No strategies available</p>
          )}
        </div>
      </div>

      {/* Capital & Risk */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Capital ($)</label>
          <input
            type="number"
            value={capital}
            onChange={e => setCapital(e.target.value)}
            min="1"
            step="100"
            className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 outline-none"
            id="backtest-capital"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Risk (%)</label>
          <input
            type="number"
            value={risk}
            onChange={e => setRisk(e.target.value)}
            min="0.1"
            max="100"
            step="0.1"
            className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 outline-none"
            id="backtest-risk"
          />
        </div>
      </div>

      {/* Validation Error */}
      {validationError && (
        <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-md px-3 py-2">
          {validationError}
        </p>
      )}

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={loading}
        className={`w-full py-2.5 rounded-lg font-medium text-sm transition-all ${
          loading
            ? 'bg-slate-600 text-slate-400 cursor-not-allowed'
            : 'bg-emerald-600 text-white hover:bg-emerald-500 active:scale-[0.98]'
        }`}
        id="run-backtest-btn"
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <span className="w-4 h-4 border-2 border-slate-400/30 border-t-slate-400 rounded-full animate-spin" />
            Running...
          </span>
        ) : (
          '▶ Run Backtest'
        )}
      </button>
    </div>
  );
}
