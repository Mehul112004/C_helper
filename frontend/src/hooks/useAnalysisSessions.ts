import { useState, useCallback, useEffect } from 'react';
import { apiClient } from '../api/client';
import type { AnalysisSession, Strategy } from '../types/signals';

interface UseAnalysisSessionsReturn {
  sessions: AnalysisSession[];
  strategies: Strategy[];
  startSession: (symbol: string, strategyNames: string[], timeframes?: string[]) => Promise<AnalysisSession>;
  stopSession: (sessionId: string) => Promise<void>;
  isLoading: boolean;
  error: string | null;
  canStartNew: boolean;
  setSessions: React.Dispatch<React.SetStateAction<AnalysisSession[]>>;
}

/**
 * Hook for managing live analysis sessions.
 * Provides CRUD operations and tracks available strategies.
 */
export function useAnalysisSessions(): UseAnalysisSessionsReturn {
  const [sessions, setSessions] = useState<AnalysisSession[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch active sessions and strategies on mount
  useEffect(() => {
    const fetchInitial = async () => {
      try {
        const [sessRes, stratRes] = await Promise.all([
          apiClient.get('/signals/sessions'),
          apiClient.get('/strategies'),
        ]);
        setSessions(sessRes.data.sessions || []);
        setStrategies(
          (stratRes.data.strategies || []).filter((s: Strategy) => s.enabled)
        );
      } catch (err) {
        console.error('[Sessions] Failed to fetch initial data:', err);
      }
    };
    fetchInitial();
  }, []);

  const startSession = useCallback(async (symbol: string, strategyNames: string[], timeframes?: string[]) => {
    setIsLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.post('/signals/sessions', {
        symbol,
        strategy_names: strategyNames,
        timeframes,
      });
      const session = data.session as AnalysisSession;
      setSessions((prev) => [...prev, session]);
      return session;
    } catch (err: any) {
      const msg = err.response?.data?.error || err.message || 'Failed to start session';
      setError(msg);
      throw new Error(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const stopSession = useCallback(async (sessionId: string) => {
    setIsLoading(true);
    setError(null);
    try {
      await apiClient.delete(`/signals/sessions/${sessionId}`);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    } catch (err: any) {
      const msg = err.response?.data?.error || err.message || 'Failed to stop session';
      setError(msg);
      throw new Error(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const canStartNew = sessions.filter((s) => s.status === 'active').length < 10;

  return {
    sessions,
    strategies,
    startSession,
    stopSession,
    isLoading,
    error,
    canStartNew,
    setSessions,
  };
}
