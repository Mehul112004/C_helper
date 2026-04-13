import { useEffect, useRef, useState, useCallback } from 'react';
import type { SSEEventType } from '../types/signals';

const SSE_URL = 'http://localhost:5001/api/signals/stream';
const RECONNECT_DELAY = 3000;

interface SSEHookReturn {
  connected: boolean;
  reconnecting: boolean;
}

type EventHandler = (eventType: SSEEventType, data: Record<string, unknown>) => void;

/**
 * React hook for SSE connection with auto-reconnect.
 * Subscribes to the backend SSE stream and dispatches events to the handler.
 */
export function useSSE(onEvent: EventHandler): SSEHookReturn {
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = new EventSource(SSE_URL);
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnected(true);
      setReconnecting(false);
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
      eventSourceRef.current = null;
      setReconnecting(true);
      setTimeout(connect, RECONNECT_DELAY);
    };

    // Listen for all event types
    const eventTypes: SSEEventType[] = [
      'setup_detected',
      'setup_expired',
      'setup_updated',
      'session_started',
      'session_stopped',
      'candle_close',
      'price_update',
    ];

    eventTypes.forEach((type) => {
      es.addEventListener(type, (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          onEventRef.current(type, data);
        } catch (err) {
          console.error(`[SSE] Failed to parse ${type} event:`, err);
        }
      });
    });
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [connect]);

  return { connected, reconnecting };
}
