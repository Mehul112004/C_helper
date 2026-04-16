import { useState } from 'react';
import { TrendingUp, TrendingDown, Clock, XCircle } from 'lucide-react';
import type { RejectedSignal } from '../../types/signals';

interface RejectedCardProps {
  signal: RejectedSignal;
}

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const detected = new Date(dateStr).getTime();
  const diffMs = now - detected;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function RejectedCard({ signal }: RejectedCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const isLong = signal.direction === 'LONG';

  return (
    <div 
      className={`relative rounded-xl border border-red-500/30 bg-slate-800/80 p-4 transition-all duration-300 hover:border-red-500/60 shadow-lg shadow-red-900/10 cursor-pointer ${isExpanded ? 'scale-105 z-10' : ''}`}
      onClick={() => setIsExpanded(!isExpanded)}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-white">{signal.symbol}</span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 font-mono">
            {signal.timeframe}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`
              flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full
              ${isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}
            `}
          >
            {isLong ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {signal.direction}
          </span>
        </div>
      </div>

      <p className="text-xs text-slate-400 mb-3">{signal.strategy_name}</p>

      {/* LLM Status Banner */}
      <div className="mb-3 flex items-start gap-2 p-2 rounded bg-slate-900/50 border-l-2 border-red-500 text-red-400">
        <XCircle size={14} className="mt-0.5 flex-shrink-0" />
        <div>
          <p className="text-xs font-semibold">LLM Rejected</p>
          <p className={`text-xs text-slate-300 mt-0.5 ${isExpanded ? '' : 'line-clamp-2'}`} title={signal.reasoning_text}>{signal.reasoning_text}</p>
        </div>
      </div>

      {/* Entry / SL / TP (if present) */}
      <div className="grid grid-cols-4 gap-1 text-xs mb-3 bg-slate-900/50 p-2 rounded">
        <div>
          <span className="text-slate-500">Entry</span>
          <p className="text-white font-mono">{signal.entry?.toLocaleString() ?? '-'}</p>
        </div>
        <div>
          <span className="text-red-400">SL</span>
          <p className="text-red-300 font-mono">{signal.sl?.toLocaleString() ?? '-'}</p>
        </div>
        <div>
          <span className="text-emerald-400">TP1</span>
          <p className="text-emerald-300 font-mono">{signal.tp1?.toLocaleString() ?? '-'}</p>
        </div>
        <div>
          <span className="text-emerald-500">TP2</span>
          <p className="text-emerald-400 font-mono">{signal.tp2?.toLocaleString() ?? '-'}</p>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-slate-700/50">
        <span className="flex items-center gap-1">
          <Clock size={11} />
          {timeAgo(signal.created_at)}
        </span>
      </div>
    </div>
  );
}
