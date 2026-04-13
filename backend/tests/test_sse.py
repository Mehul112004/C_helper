"""
Unit tests for SSEManager (app/core/sse.py)
Tests thread-safe pub/sub, multiple subscribers, keepalive, and dead-subscriber cleanup.
"""

import queue
import threading
import time

from app.core.sse import SSEManager


class TestSSEManagerSubscription:
    """Test subscribe/unsubscribe lifecycle."""

    def test_subscribe_returns_queue(self):
        mgr = SSEManager()
        q = mgr.subscribe()
        assert isinstance(q, queue.Queue)

    def test_subscribe_increments_count(self):
        mgr = SSEManager()
        assert mgr.subscriber_count() == 0
        q1 = mgr.subscribe()
        assert mgr.subscriber_count() == 1
        q2 = mgr.subscribe()
        assert mgr.subscriber_count() == 2

    def test_unsubscribe_decrements_count(self):
        mgr = SSEManager()
        q = mgr.subscribe()
        assert mgr.subscriber_count() == 1
        mgr.unsubscribe(q)
        assert mgr.subscriber_count() == 0

    def test_unsubscribe_nonexistent_queue_is_safe(self):
        mgr = SSEManager()
        q = queue.Queue()
        mgr.unsubscribe(q)  # Should not raise
        assert mgr.subscriber_count() == 0

    def test_double_unsubscribe_is_safe(self):
        mgr = SSEManager()
        q = mgr.subscribe()
        mgr.unsubscribe(q)
        mgr.unsubscribe(q)  # Should not raise
        assert mgr.subscriber_count() == 0


class TestSSEManagerPublish:
    """Test event publishing to subscribers."""

    def test_publish_delivers_to_single_subscriber(self):
        mgr = SSEManager()
        q = mgr.subscribe()
        mgr.publish("test_event", {"key": "value"})

        event = q.get_nowait()
        assert event["type"] == "test_event"
        assert event["data"] == {"key": "value"}

    def test_publish_delivers_to_multiple_subscribers(self):
        mgr = SSEManager()
        q1 = mgr.subscribe()
        q2 = mgr.subscribe()
        q3 = mgr.subscribe()

        mgr.publish("setup_detected", {"id": "abc"})

        for q in [q1, q2, q3]:
            event = q.get_nowait()
            assert event["type"] == "setup_detected"
            assert event["data"]["id"] == "abc"

    def test_publish_to_no_subscribers_is_safe(self):
        mgr = SSEManager()
        mgr.publish("test", {"data": True})  # Should not raise

    def test_unsubscribed_queue_does_not_receive(self):
        mgr = SSEManager()
        q = mgr.subscribe()
        mgr.unsubscribe(q)
        mgr.publish("event", {"x": 1})
        assert q.empty()

    def test_multiple_events_queued(self):
        mgr = SSEManager()
        q = mgr.subscribe()

        mgr.publish("event_a", {"n": 1})
        mgr.publish("event_b", {"n": 2})
        mgr.publish("event_c", {"n": 3})

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        assert len(events) == 3
        assert events[0]["type"] == "event_a"
        assert events[1]["type"] == "event_b"
        assert events[2]["type"] == "event_c"


class TestSSEManagerFullQueue:
    """Test behavior when subscriber queue is full."""

    def test_full_queue_drops_event_and_removes_subscriber(self):
        mgr = SSEManager()
        # Create a queue with maxsize=1 to simulate a slow consumer
        small_q = queue.Queue(maxsize=1)
        with mgr._lock:
            mgr._subscribers.append(small_q)

        # Fill the queue
        mgr.publish("event1", {"x": 1})
        assert mgr.subscriber_count() == 1

        # This should overflow and remove the subscriber
        mgr.publish("event2", {"x": 2})
        assert mgr.subscriber_count() == 0


class TestSSEManagerKeepalive:
    """Test keepalive mechanism."""

    def test_keepalive_sends_none(self):
        mgr = SSEManager()
        q = mgr.subscribe()
        mgr.send_keepalive()

        event = q.get_nowait()
        assert event is None

    def test_keepalive_to_empty_subscribers_is_safe(self):
        mgr = SSEManager()
        mgr.send_keepalive()  # Should not raise


class TestSSEManagerThreadSafety:
    """Test concurrent access from multiple threads."""

    def test_concurrent_publish_and_subscribe(self):
        mgr = SSEManager()
        received = []
        errors = []

        def subscriber_thread():
            q = mgr.subscribe()
            try:
                event = q.get(timeout=2)
                received.append(event)
            except queue.Empty:
                errors.append("timeout")
            finally:
                mgr.unsubscribe(q)

        def publisher_thread():
            time.sleep(0.1)  # Let subscribers connect first
            for i in range(5):
                mgr.publish("test", {"i": i})

        threads = []
        for _ in range(3):
            t = threading.Thread(target=subscriber_thread)
            threads.append(t)
            t.start()

        pub = threading.Thread(target=publisher_thread)
        pub.start()

        for t in threads:
            t.join(timeout=3)
        pub.join(timeout=3)

        assert len(errors) == 0
        assert len(received) == 3  # Each subscriber gets at least one event
        assert mgr.subscriber_count() == 0  # All unsubscribed


class TestSSEManagerEventTypes:
    """Test all expected Phase 4 event types."""

    def test_all_event_types_deliverable(self):
        mgr = SSEManager()
        q = mgr.subscribe()

        event_types = [
            "setup_detected",
            "setup_expired",
            "setup_updated",
            "session_started",
            "session_stopped",
            "candle_close",
            "price_update",
        ]

        for et in event_types:
            mgr.publish(et, {"type_name": et})

        received_types = []
        while not q.empty():
            event = q.get_nowait()
            received_types.append(event["type"])

        assert received_types == event_types
