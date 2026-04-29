
import { TrendingUp, TrendingDown, Clock, AlertTriangle } from 'lucide-react';
import type { WatchingSetup } from '../../types/signals';
import MiniChart from './MiniChart';

interface WatchingCardProps {
  setup: WatchingSetup;
}

function formatTimeIST(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleString('en-US', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true
  }) + ' IST';
}

function confidenceColor(c: number): string {
  if (c >= 0.8) return 'text-emerald-400';
  if (c >= 0.65) return 'text-yellow-400';
  return 'text-red-400';
}

function confidenceBarColor(c: number): string {
  if (c >= 0.8) return 'bg-emerald-500';
  if (c >= 0.65) return 'bg-yellow-500';
  return 'bg-red-500';
}

/**
 * Individual watching card showing a detected setup with live info.
 */
export default function WatchingCard({ setup }: WatchingCardProps) {
  const isExpiring = setup.candles_since_detected >= setup.expiry_candles - 1;
  const isLong = setup.direction === 'LONG';
  const timeDisplay = formatTimeIST(setup.detected_at);

  return (
    <div
      className={`
        relative rounded-xl border p-4 transition-all duration-500
        ${isExpiring
          ? 'border-red-500/40 bg-red-500/5 opacity-75'
          : 'border-slate-600/50 bg-slate-800/60 hover:border-slate-500/60 hover:bg-slate-800/80'
        }
        backdrop-blur-sm
      `}
    >
      {/* Header: Symbol + Timeframe + Direction */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-white">{setup.symbol}</span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 font-mono">
            {setup.timeframe}
          </span>
        </div>
        <span
          className={`
            flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full
            ${isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}
          `}
        >
          {isLong ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          {setup.direction}
        </span>
      </div>

      {/* Strategy Name */}
      <p className="text-xs text-slate-400 mb-2">{setup.strategy_name}</p>

      {/* Notes */}
      {setup.notes && (
        <p className="text-xs text-slate-500 mb-2 italic truncate">{setup.notes}</p>
      )}

      {/* Mini Chart */}
      <MiniChart symbol={setup.symbol} timeframe={setup.timeframe} entry={setup.entry} />

      {/* Confidence Bar */}
      <div className="mt-3 mb-2">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-slate-400">Confidence</span>
          <span className={`font-bold ${confidenceColor(setup.confidence)}`}>
            {Math.round(setup.confidence * 100)}%
          </span>
        </div>
        <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-300 ${confidenceBarColor(setup.confidence)}`}
            style={{ width: `${Math.min(setup.confidence * 100, 100)}%` }}
          />
        </div>
      </div>

      {/* Entry / SL / TP */}
      {setup.entry && (
        <div className="grid grid-cols-2 gap-2 text-xs mb-2">
          <div>
            <span className="text-slate-500">Entry</span>
            <p className="text-white font-mono">{setup.entry.toLocaleString()}</p>
          </div>
          {setup.sl && (
            <div>
              <span className="text-red-400">SL</span>
              <p className="text-red-300 font-mono">{setup.sl.toLocaleString()}</p>
            </div>
          )}
          {setup.tp1 && (
            <div>
              <span className="text-emerald-400">TP1</span>
              <p className="text-emerald-300 font-mono">{setup.tp1.toLocaleString()}</p>
            </div>
          )}
          {setup.tp2 && (
            <div>
              <span className="text-emerald-500">TP2</span>
              <p className="text-emerald-400 font-mono">{setup.tp2.toLocaleString()}</p>
            </div>
          )}
        </div>
      )}

      {/* Footer: Time Elapsed + Expiry */}
      <div className="flex items-center justify-between text-xs text-slate-400 mt-2 pt-2 border-t border-slate-700/50">
        <span className="flex items-center gap-1">
          <Clock size={11} />
          {timeDisplay}
        </span>
        <span className={`flex items-center gap-1 ${isExpiring ? 'text-red-400' : ''}`}>
          {isExpiring && <AlertTriangle size={11} />}
          Exp: {setup.candles_since_detected}/{setup.expiry_candles}
        </span>
      </div>
    </div>
  );
}
