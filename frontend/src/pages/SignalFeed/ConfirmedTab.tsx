import { useState } from 'react';
import { CheckCircle } from 'lucide-react';
import type { ConfirmedSignal } from '../../types/signals';
import ConfirmedCard from '../../components/ConfirmedCard/ConfirmedCard';

interface ConfirmedTabProps {
  signals: ConfirmedSignal[];
  activeSessionIds: string[];
}

export default function ConfirmedTab({ signals, activeSessionIds }: ConfirmedTabProps) {
  const [showAll, setShowAll] = useState(false);

  // Filter signals: active sessions vs all
  const displaySignals = showAll 
    ? signals 
    : signals.filter(s => activeSessionIds.includes(s.session_id));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-medium text-white flex items-center gap-2">
          <CheckCircle size={18} className="text-emerald-400" />
          Confirmed Pipeline
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-400">Show All History</span>
          <button
            onClick={() => setShowAll(!showAll)}
            className={`w-10 h-5 rounded-full relative transition-[background-color] ${
              showAll ? 'bg-emerald-500' : 'bg-slate-700'
            }`}
          >
            <div
              className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-[transform] ${
                showAll ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      </div>

      {displaySignals.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-500">
          <CheckCircle size={40} className="mb-3 opacity-30" />
          <p className="text-sm font-medium">No confirmed signals</p>
          <p className="text-xs mt-1 text-slate-600">
            {showAll ? 'The LLM has not confirmed any setups yet.' : 'No confirmed signals from active sessions. Toggle "Show All" to view history.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {displaySignals.map(signal => (
            <ConfirmedCard key={signal.id} signal={signal} />
          ))}
        </div>
      )}
    </div>
  );
}
