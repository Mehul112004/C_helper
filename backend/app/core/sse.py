"""
SSE (Server-Sent Events) Manager
Thread-safe pub/sub for pushing real-time events to frontend clients.

Events flow:
  Backend components → SSEManager.publish() → subscriber queues → Flask SSE endpoint → EventSource clients

Supported event types:
  - setup_detected: New watching card created
  - setup_expired: Watching card expired
  - setup_updated: Existing watching card refreshed (dedup)
  - session_started: Analysis session started
  - session_stopped: Analysis session stopped
  - candle_close: Live candle close notification
  - price_update: Live price tick for a symbol
"""

import queue
import threading
import time
from typing import Optional


class SSEManager:
    """
    Thread-safe pub/sub manager for Server-Sent Events.

    Multiple frontend clients can subscribe (each gets their own queue).
    Backend components publish events via publish().
    The Flask SSE endpoint reads from subscriber queues.
    """

    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        """
        Create a new subscriber queue and register it.

        Returns:
            A queue.Queue that will receive published events.
            Each event is a dict with 'type' and 'data' keys,
            or None for keepalive signals.
        """
        q = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        """
        Remove a subscriber queue. Called when SSE connection closes.

        Args:
            q: The queue returned by subscribe()
        """
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass  # Already removed

    def publish(self, event_type: str, data: dict):
        """
        Publish an event to all active subscribers.

        Events that cannot be delivered (full queue) are dropped silently
        to prevent slow clients from blocking the system.

        Args:
            event_type: SSE event name (e.g. 'setup_detected', 'price_update')
            data: JSON-serializable dict payload
        """
        event = {'type': event_type, 'data': data}
        with self._lock:
            dead_subscribers = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    # Drop event for slow consumer rather than blocking
                    dead_subscribers.append(q)

            # Clean up any overflowed subscribers
            for q in dead_subscribers:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass

    def subscriber_count(self) -> int:
        """Return the current number of active subscribers."""
        with self._lock:
            return len(self._subscribers)

    def send_keepalive(self):
        """
        Send a keepalive (None) to all subscribers.
        Used by the SSE endpoint when no events arrive within the timeout.
        """
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass


# Module-level singleton
sse_manager = SSEManager()
