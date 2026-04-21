import { useState, useEffect } from 'react';
import { fetchDatasets } from '../../api/client';
import { ChevronDown, Layers, TrendingUp, BarChart3 } from 'lucide-react';

interface Dataset {
  symbol: string;
  timeframe: string;
  count: number;
}

const ALL_TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d'];
const CANDLE_LIMITS = [100, 250, 500, 1000, 2500];

interface ChartControlsProps {
  symbol: string;
  timeframe: string;
  limit: number;
  showSRZones: boolean;
  minStrength: number;
  showEMA: boolean;
  emaVisible: Record<string, boolean>;
  onSymbolChange: (s: string) => void;
  onTimeframeChange: (tf: string) => void;
  onLimitChange: (l: number) => void;
  onToggleSRZones: () => void;
  onMinStrengthChange: (v: number) => void;
  onToggleEMA: () => void;
  onToggleEMALine: (key: string) => void;
}

export default function ChartControls({
  symbol,
  timeframe,
  limit,
  showSRZones,
  minStrength,
  showEMA,
  emaVisible,
  onSymbolChange,
  onTimeframeChange,
  onLimitChange,
  onToggleSRZones,
  onMinStrengthChange,
  onToggleEMA,
  onToggleEMALine,
}: ChartControlsProps) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);

  useEffect(() => {
    fetchDatasets()
      .then((d: Dataset[]) => setDatasets(d))
      .catch(console.error);
  }, []);

  // Unique symbols from datasets
  const symbols = [...new Set(datasets.map(d => d.symbol))].sort();

  // Available timeframes for current symbol
  const availableTimeframes = new Set(
    datasets.filter(d => d.symbol === symbol).map(d => d.timeframe)
  );

  // Auto-select first symbol if none set
  useEffect(() => {
    if (!symbol && symbols.length > 0) {
      onSymbolChange(symbols[0]);
    }
  }, [symbol, symbols, onSymbolChange]);

  // Auto-select first available timeframe if current is not available
  useEffect(() => {
    if (symbol && availableTimeframes.size > 0 && !availableTimeframes.has(timeframe)) {
      const first = ALL_TIMEFRAMES.find(tf => availableTimeframes.has(tf));
      if (first) onTimeframeChange(first);
    }
  }, [symbol, timeframe, availableTimeframes, onTimeframeChange]);

  const EMA_KEYS = [
    { key: 'ema_9', label: '9', color: '#f59e0b' },
    { key: 'ema_21', label: '21', color: '#3b82f6' },
    { key: 'ema_50', label: '50', color: '#8b5cf6' },
    { key: 'ema_200', label: '200', color: '#ef4444' },
  ];

  return (
    <div id="chart-controls" className="flex items-center gap-3 px-5 py-3 border-b border-slate-700/80 bg-slate-800/60 backdrop-blur-sm flex-wrap">
      {/* Symbol Selector */}
      <div className="relative" id="symbol-selector">
        <select
          value={symbol}
          onChange={e => onSymbolChange(e.target.value)}
          className="appearance-none bg-slate-700/80 border border-slate-600/60 text-white text-sm font-semibold rounded-lg px-4 py-2 pr-8 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-500/60 transition-all cursor-pointer hover:bg-slate-700"
        >
          {symbols.length === 0 && <option value="">Loading…</option>}
          {symbols.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
      </div>

      {/* Timeframe Pills */}
      <div className="flex rounded-lg border border-slate-600/60 overflow-hidden" id="timeframe-pills">
        {ALL_TIMEFRAMES.map(tf => {
          const available = availableTimeframes.has(tf);
          const active = tf === timeframe;
          return (
            <button
              key={tf}
              onClick={() => available && onTimeframeChange(tf)}
              disabled={!available}
              className={`px-3 py-1.5 text-xs font-semibold transition-all ${
                active
                  ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40'
                  : available
                    ? 'text-slate-400 hover:text-white hover:bg-slate-700/60'
                    : 'text-slate-600 cursor-not-allowed opacity-40'
              } ${tf !== ALL_TIMEFRAMES[ALL_TIMEFRAMES.length - 1] ? 'border-r border-slate-600/60' : ''}`}
              id={`tf-${tf}`}
            >
              {tf.toUpperCase()}
            </button>
          );
        })}
      </div>

      {/* Candle Limit */}
      <div className="relative" id="limit-selector">
        <select
          value={limit}
          onChange={e => onLimitChange(Number(e.target.value))}
          className="appearance-none bg-slate-700/80 border border-slate-600/60 text-slate-300 text-xs rounded-lg px-3 py-2 pr-7 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 transition-all cursor-pointer hover:bg-slate-700"
        >
          {CANDLE_LIMITS.map(l => (
            <option key={l} value={l}>{l} candles</option>
          ))}
        </select>
        <BarChart3 size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
      </div>

      {/* Divider */}
      <div className="w-px h-6 bg-slate-600/60 mx-1" />

      {/* S/R Zone Toggle */}
      <button
        onClick={onToggleSRZones}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
          showSRZones
            ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30 shadow-[0_0_12px_rgba(16,185,129,0.1)]'
            : 'text-slate-400 border-slate-600/60 hover:text-white hover:bg-slate-700/60'
        }`}
        id="toggle-sr-zones"
      >
        <Layers size={13} />
        S/R Zones
      </button>

      {/* Strength Slider (visible when S/R zones are on) */}
      {showSRZones && (
        <div className="flex items-center gap-2" id="strength-slider">
          <span className="text-[10px] text-slate-500 uppercase tracking-wider">Min</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={minStrength}
            onChange={e => onMinStrengthChange(parseFloat(e.target.value))}
            className="w-20 h-1 accent-emerald-500 cursor-pointer"
          />
          <span className="text-xs text-slate-400 font-mono w-7">{minStrength.toFixed(2)}</span>
        </div>
      )}

      {/* Divider */}
      <div className="w-px h-6 bg-slate-600/60 mx-1" />

      {/* EMA Toggle */}
      <button
        onClick={onToggleEMA}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
          showEMA
            ? 'bg-blue-500/15 text-blue-400 border-blue-500/30 shadow-[0_0_12px_rgba(59,130,246,0.1)]'
            : 'text-slate-400 border-slate-600/60 hover:text-white hover:bg-slate-700/60'
        }`}
        id="toggle-ema"
      >
        <TrendingUp size={13} />
        EMA
      </button>

      {/* EMA Period Toggles */}
      {showEMA && (
        <div className="flex gap-1" id="ema-period-toggles">
          {EMA_KEYS.map(({ key, label, color }) => (
            <button
              key={key}
              onClick={() => onToggleEMALine(key)}
              className={`px-2 py-1 rounded text-[10px] font-bold transition-all border ${
                emaVisible[key]
                  ? 'border-opacity-50 shadow-sm'
                  : 'opacity-30 border-transparent hover:opacity-60'
              }`}
              style={{
                color: emaVisible[key] ? color : '#94a3b8',
                borderColor: emaVisible[key] ? color : 'transparent',
                backgroundColor: emaVisible[key] ? `${color}15` : 'transparent',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
