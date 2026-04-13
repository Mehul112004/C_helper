import { useState, useCallback, useEffect } from 'react';
import { Eye, CheckCircle } from 'lucide-react';
import { useSSE } from '../../hooks/useSSE';
import { useAnalysisSessions } from '../../hooks/useAnalysisSessions';
import SessionPanel from './SessionPanel';
import WatchingTab from './WatchingTab';
import ConfirmedTab from './ConfirmedTab';
import type { WatchingSetup, SSEEventType, PriceUpdate } from '../../types/signals';
import { apiClient } from '../../api/client';

type Tab = 'watching' | 'confirmed';

/**
 * Main Signal Feed page — the primary daily-use page.
 * Contains session panel, tab navigation, and watching/confirmed content.
 */
export default function SignalFeed() {
  const [activeTab, setActiveTab] = useState<Tab>('watching');
  const [watchingSetups, setWatchingSetups] = useState<WatchingSetup[]>([]);

  const {
    sessions,
    strategies,
    startSession,
    stopSession,
    isLoading,
    canStartNew,
    setSessions,
  } = useAnalysisSessions();

  // Fetch initial watching setups
  useEffect(() => {
    apiClient
      .get('/signals/watching')
      .then((res) => setWatchingSetups(res.data.setups || []))
      .catch(() => {});
  }, []);

  // SSE event handler
  const handleSSEEvent = useCallback(
    (eventType: SSEEventType, data: Record<string, unknown>) => {
      switch (eventType) {
        case 'setup_detected': {
          const setup = data as unknown as WatchingSetup;
          setWatchingSetups((prev) => [setup, ...prev]);
          break;
        }
        case 'setup_updated': {
          const updated = data as unknown as WatchingSetup;
          setWatchingSetups((prev) =>
            prev.map((s) => (s.id === updated.id ? updated : s))
          );
          break;
        }
        case 'setup_expired': {
          const expired = data as unknown as WatchingSetup;
          setWatchingSetups((prev) =>
            prev.map((s) => (s.id === expired.id ? { ...s, status: 'EXPIRED' as const } : s))
          );
          // Remove expired cards after fade-out animation
          setTimeout(() => {
            setWatchingSetups((prev) => prev.filter((s) => s.id !== expired.id));
          }, 2000);
          break;
        }
        case 'session_stopped': {
          const sessionId = (data as any).session_id;
          setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
          setWatchingSetups((prev) => prev.filter((s) => s.session_id !== sessionId));
          break;
        }
        case 'price_update': {
          const price = data as unknown as PriceUpdate;
          setSessions((prev) =>
            prev.map((s) =>
              s.session_id === price.session_id
                ? { ...s, live_price: price.price, live_price_updated_at: price.timestamp }
                : s
            )
          );
          break;
        }
        default:
          break;
      }
    },
    [setSessions]
  );

  const { connected } = useSSE(handleSSEEvent);

  const handleStartSession = useCallback(
    async (sym: string, strats: string[], timeframes?: string[]) => {
      try {
        await startSession(sym, strats, timeframes);
      } catch {
        // Error is handled in the hook
      }
    },
    [startSession]
  );

  const handleStopSession = useCallback(
    async (sessionId: string) => {
      try {
        await stopSession(sessionId);
      } catch {
        // Error is handled in the hook
      }
    },
    [stopSession]
  );

  const watchingCount = watchingSetups.filter((s) => s.status === 'WATCHING').length;

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      {/* Page Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white mb-1">Signal Feed</h1>
        <p className="text-sm text-slate-400">
          Real-time market scanning — detect setups as they form
        </p>
      </div>

      {/* Session Panel */}
      <SessionPanel
        sessions={sessions}
        strategies={strategies}
        canStartNew={canStartNew}
        isLoading={isLoading}
        connected={connected}
        onStartSession={handleStartSession}
        onStopSession={handleStopSession}
      />

      {/* Tab Navigation */}
      <div className="flex items-center gap-1 mb-6 border-b border-slate-700/50">
        <button
          onClick={() => setActiveTab('watching')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition ${
            activeTab === 'watching'
              ? 'border-emerald-500 text-emerald-400'
              : 'border-transparent text-slate-400 hover:text-slate-300'
          }`}
        >
          <Eye size={16} />
          Watching
          {watchingCount > 0 && (
            <span className="ml-1 text-xs px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400">
              {watchingCount}
            </span>
          )}
        </button>
        <button
          onClick={() => setActiveTab('confirmed')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition ${
            activeTab === 'confirmed'
              ? 'border-emerald-500 text-emerald-400'
              : 'border-transparent text-slate-400 hover:text-slate-300'
          }`}
        >
          <CheckCircle size={16} />
          Confirmed
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === 'watching' ? (
        <WatchingTab setups={watchingSetups} />
      ) : (
        <ConfirmedTab />
      )}
    </div>
  );
}
