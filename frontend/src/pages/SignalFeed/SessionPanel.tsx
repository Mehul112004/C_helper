import { useState } from 'react';
import {
  Play,
  Square,
  Wifi,
  WifiOff,
  Loader2,
  Plus,
  X,
} from 'lucide-react';
import type { AnalysisSession, Strategy } from '../../types/signals';

interface SessionPanelProps {
  sessions: AnalysisSession[];
  strategies: Strategy[];
  canStartNew: boolean;
  isLoading: boolean;
  connected: boolean;
  onStartSession: (symbol: string, strategyNames: string[], timeframes?: string[]) => void;
  onStopSession: (sessionId: string) => void;
}

/**
 * Session control panel — shows active sessions with live price,
 * and a form to start new sessions.
 */
export default function SessionPanel({
  sessions,
  strategies,
  canStartNew,
  isLoading,
  connected,
  onStartSession,
  onStopSession,
}: SessionPanelProps) {
  const [showForm, setShowForm] = useState(false);
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [selectedTimeframes, setSelectedTimeframes] = useState<string[]>(['1h']);

  const AVAILABLE_TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d'];

  const handleStart = () => {
    if (!symbol || selectedStrategies.length === 0 || selectedTimeframes.length === 0) return;
    onStartSession(symbol.toUpperCase(), selectedStrategies, selectedTimeframes);
    setShowForm(false);
    setSymbol('BTCUSDT');
    setSelectedStrategies([]);
    setSelectedTimeframes(['1h']);
  };

  const toggleStrategy = (name: string) => {
    setSelectedStrategies((prev) =>
      prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name]
    );
  };

  const toggleTimeframe = (tf: string) => {
    setSelectedTimeframes((prev) =>
      prev.includes(tf) ? prev.filter((t) => t !== tf) : [...prev, tf]
    );
  };

  const activeSessions = sessions.filter((s) => s.status === 'active');

  return (
    <div className="mb-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-white">Live Analysis</h2>
          <span
            className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${
              connected
                ? 'bg-emerald-500/20 text-emerald-400'
                : 'bg-red-500/20 text-red-400'
            }`}
          >
            {connected ? <Wifi size={10} /> : <WifiOff size={10} />}
            {connected ? 'Live' : 'Disconnected'}
          </span>
        </div>

        {canStartNew && !showForm && (
          <button
            onClick={() => setShowForm(true)}
            disabled={isLoading}
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition disabled:opacity-50"
          >
            <Plus size={14} />
            Start Session
          </button>
        )}
      </div>

      {/* Session Cards */}
      <div className="space-y-2 mb-4">
        {activeSessions.map((session) => (
          <div
            key={session.session_id}
            className="flex items-center justify-between px-4 py-3 rounded-xl bg-slate-800/70 border border-slate-700/50 backdrop-blur-sm"
          >
            <div className="flex items-center gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-white">{session.symbol}</span>
                  {session.live_price !== null && (
                    <span className="text-sm font-mono text-emerald-400">
                      ${session.live_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400 mt-0.5">
                  {session.strategy_names.join(', ')} · {session.timeframes.join(', ')}
                </p>
              </div>
            </div>
            <button
              onClick={() => onStopSession(session.session_id)}
              disabled={isLoading}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition disabled:opacity-50"
            >
              <Square size={10} />
              Stop
            </button>
          </div>
        ))}

        {activeSessions.length === 0 && !showForm && (
          <div className="text-center py-8 text-slate-500 text-sm">
            <Play size={24} className="mx-auto mb-2 opacity-40" />
            No active sessions — start one to begin live analysis
          </div>
        )}
      </div>

      {/* New Session Form */}
      {showForm && (
        <div className="rounded-xl border border-slate-600/50 bg-slate-800/80 p-4 backdrop-blur-sm">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white">New Analysis Session</h3>
            <button onClick={() => setShowForm(false)} className="text-slate-400 hover:text-white">
              <X size={16} />
            </button>
          </div>

          {/* Symbol Input */}
          <div className="mb-3">
            <label className="text-xs text-slate-400 mb-1 block">Trading Pair</label>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="e.g. BTCUSDT"
              className="w-full px-3 py-2 text-sm rounded-lg bg-slate-700 border border-slate-600 text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition"
            />
          </div>

          {/* Strategy Selection */}
          <div className="mb-4">
            <label className="text-xs text-slate-400 mb-2 block">Strategies</label>
            <div className="flex flex-wrap gap-2">
              {strategies.map((strat) => (
                <button
                  key={strat.name}
                  onClick={() => toggleStrategy(strat.name)}
                  className={`text-xs px-2.5 py-1 rounded-lg border transition ${
                    selectedStrategies.includes(strat.name)
                      ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400'
                      : 'bg-slate-700/50 border-slate-600/50 text-slate-400 hover:border-slate-500'
                  }`}
                >
                  {strat.name}
                </button>
              ))}
            </div>
          </div>

          {/* Timeframe Selection */}
          <div className="mb-4">
            <label className="text-xs text-slate-400 mb-2 block">Timeframes</label>
            <div className="flex flex-wrap gap-2">
              {AVAILABLE_TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  onClick={() => toggleTimeframe(tf)}
                  className={`text-xs px-2.5 py-1 rounded-lg border transition ${
                    selectedTimeframes.includes(tf)
                      ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400'
                      : 'bg-slate-700/50 border-slate-600/50 text-slate-400 hover:border-slate-500'
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>

          {/* Start Button */}
          <button
            onClick={handleStart}
            disabled={!symbol || selectedStrategies.length === 0 || selectedTimeframes.length === 0 || isLoading}
            className="w-full flex items-center justify-center gap-2 text-sm font-medium py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isLoading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            Start Scanning {symbol || '...'}
          </button>
        </div>
      )}
    </div>
  );
}
