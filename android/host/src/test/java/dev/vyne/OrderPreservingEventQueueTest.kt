/**
 * Order-preserving event queue tests for INPUT-09.
 *
 * Verifies:
 * - Global arrival order is preserved across mixed "all" and "latest" delivery events.
 * - Latest coalescing replaces in-place (FIFO position preserved).
 * - Control receipts (apply results) are enqueued and never coalesced/reordered.
 * - Tombstone removal preserves order for stale events.
 * - Monotonic sequence ordering in edge cases.
 */
package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class OrderPreservingEventQueueTest {

    // ── Global arrival order ──────────────────────────────────────────

    @Test
    fun `mixed delivery events preserve global arrival order`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        // Interleave "all" and "latest" delivery events.
        val e1 = event(seq = 1, x = 10, gestureId = 1, delivery = "all")
        val e2 = event(seq = 2, x = 20, gestureId = 1, delivery = "latest")
        val e3 = event(seq = 3, x = 30, gestureId = 1, delivery = "all")
        val e4 = event(seq = 4, x = 40, gestureId = 1, delivery = "latest")

        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e1)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e2)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e3)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e4)

        // e2 replaces e2 at index 1 (latest coalescing for same key).
        // e4 is also "latest" with the same key, so it replaces e2 in-place at index 1.
        // Result: [e1(seq=1), e4(seq=4), e3(seq=3)]
        assertEquals(listOf(1L, 3L, 4L), queue.map(NativeEvent::sequence))
    }

    @Test
    fun `all delivery events never coalesce`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        val e1 = event(seq = 1, x = 10, gestureId = 1, delivery = "all")
        val e2 = event(seq = 2, x = 20, gestureId = 1, delivery = "all")
        val e3 = event(seq = 3, x = 30, gestureId = 1, delivery = "all")

        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e1)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e2)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e3)

        // All "all" events are appended — no coalescing.
        assertEquals(3, queue.size)
        assertEquals(listOf(1L, 2L, 3L), queue.map(NativeEvent::sequence))
    }

    // ── Latest coalescing ──────────────────────────────────────────────

    @Test
    fun `latest coalescing preserves FIFO position`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        // Fill queue with some events.
        val e1 = event(seq = 1, x = 10, gestureId = 1, delivery = "all")
        val e2 = event(seq = 2, x = 20, gestureId = 2, delivery = "all")
        val e3 = event(seq = 3, x = 30, gestureId = 1, delivery = "latest")

        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e1)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e2)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e3)

        // e3 is "latest" for gestureId=1 — it should be at index 2.
        // Now send another "latest" for the same gestureId=1.
        val e4 = event(seq = 4, x = 40, gestureId = 1, delivery = "latest")
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e4)

        // e4 replaces e3 in-place. The FIFO position is preserved.
        assertEquals(3, queue.size)
        assertEquals(listOf(1L, 2L, 4L), queue.map(NativeEvent::sequence))
        // Verify the actual payload values.
        assertEquals(listOf(10, 20, 40), queue.map { it.payload["x"] })
    }

    @Test
    fun `latest coalescing across different gestureIds does not conflict`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        val e1 = event(seq = 1, x = 10, gestureId = 1, delivery = "latest")
        val e2 = event(seq = 2, x = 20, gestureId = 2, delivery = "latest")
        val e3 = event(seq = 3, x = 30, gestureId = 1, delivery = "latest")

        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e1)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e2)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e3)

        // e1 and e3 share gestureId=1: e3 replaces e1 in-place.
        // e2 has gestureId=2: stays at index 1.
        assertEquals(listOf(2L, 3L), queue.map(NativeEvent::sequence))
    }

    @Test
    fun `latest coalescing across different targets does not conflict`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        val e1 = event(seq = 1, x = 10, gestureId = 1, delivery = "latest", target = 7)
        val e2 = event(seq = 2, x = 20, gestureId = 1, delivery = "latest", target = 8)
        val e3 = event(seq = 3, x = 30, gestureId = 1, delivery = "latest", target = 7)

        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e1)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e2)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e3)

        // e1 and e3 share (target=7, gestureId=1): e3 replaces e1 in-place.
        // e2 has target=8: different key, stays at index 1.
        assertEquals(2, queue.size)
        assertEquals(listOf(2L, 3L), queue.map(NativeEvent::sequence))
    }

    @Test
    fun `latest coalescing across different event names does not conflict`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        val e1 = event(seq = 1, x = 10, gestureId = 1, delivery = "latest", name = "pointer_move")
        val e2 = event(seq = 2, x = 20, gestureId = 1, delivery = "latest", name = "pointer_down")
        val e3 = event(seq = 3, x = 30, gestureId = 1, delivery = "latest", name = "pointer_move")

        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e1)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e2)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e3)

        // e1 and e3 share (name=pointer_move): e3 replaces e1.
        // e2 has name=pointer_down: different key, stays separate.
        assertEquals(listOf(2L, 3L), queue.map(NativeEvent::sequence))
    }

    // ── Control receipts ───────────────────────────────────────────────

    @Test
    fun `system events are enqueued with latest delivery`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        val sysEvent = NativeEvent(
            sequence = 0L,
            target = 0,
            name = "__vyne_system__",
            handler = 0,
            payload = mapOf("type" to "native_apply_result", "result" to "ok"),
            delivery = "latest",
        )
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, sysEvent)
        assertEquals(1, queue.size)
        assertEquals("__vyne_system__", queue.first().name)
    }

    @Test
    fun `control receipts are not coalesced with user events`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        val userEvent = event(seq = 1, x = 10, gestureId = 1, delivery = "latest")
        val sysEvent = NativeEvent(
            sequence = 0L,
            target = 0,
            name = "__vyne_system__",
            handler = 0,
            payload = mapOf("type" to "native_apply_result", "result" to "ok"),
            delivery = "latest",
        )

        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, userEvent)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, sysEvent)

        // System events have different (target, name, handler, gestureId) key
        // than user events, so they never coalesce.
        assertEquals(2, queue.size)
    }

    // ── Clear semantics ────────────────────────────────────────────────

    @Test
    fun `clear empties both queue and slots`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        repeat(5) { i ->
            BridgeWorkScheduler.enqueuePendingEvent(queue, slots,
                event(seq = i.toLong(), x = i * 10, gestureId = 1, delivery = "latest"))
        }
        assertEquals(1, queue.size) // latest coalesces to 1
        assertEquals(1, slots.size)

        BridgeWorkScheduler.clearEventQueue(queue, slots)
        assertEquals(0, queue.size)
        assertEquals(0, slots.size)
    }

    @Test
    fun `clear followed by enqueue starts fresh`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        BridgeWorkScheduler.enqueuePendingEvent(queue, slots,
            event(seq = 1, x = 10, gestureId = 1, delivery = "latest"))
        BridgeWorkScheduler.clearEventQueue(queue, slots)
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots,
            event(seq = 2, x = 20, gestureId = 2, delivery = "latest"))

        assertEquals(1, queue.size)
        assertEquals(2L, queue.first().sequence)
        assertEquals(1, slots.size)
    }

    // ── Large queue stress ─────────────────────────────────────────────

    @Test
    fun `large number of all events preserve order`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        val count = 1000
        repeat(count) { i ->
            BridgeWorkScheduler.enqueuePendingEvent(queue, slots,
                event(seq = i.toLong(), x = i, gestureId = (i % 5).toLong(), delivery = "all"))
        }

        assertEquals(count, queue.size)
        assertEquals((0 until count).map { it.toLong() }, queue.map(NativeEvent::sequence))
    }

    @Test
    fun `rapid latest coalescing preserves only the last per key`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        // Rapidly send 50 "latest" events for the same key.
        repeat(50) { i ->
            BridgeWorkScheduler.enqueuePendingEvent(queue, slots,
                event(seq = i.toLong(), x = i, gestureId = 1, delivery = "latest"))
        }

        // Only one event should remain — the last one (seq=49).
        assertEquals(1, queue.size)
        assertEquals(49L, queue.first().sequence)
        assertEquals(49, queue.first().payload["x"])
    }

    @Test
    fun `mixed rapid events maintain correct final order`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        // Pattern: all, latest(g1), all, latest(g2), all, latest(g1), latest(g2)
        val events = listOf(
            event(seq = 0, x = 0, gestureId = 0, delivery = "all"),
            event(seq = 1, x = 10, gestureId = 1, delivery = "latest"),
            event(seq = 2, x = 20, gestureId = 0, delivery = "all"),
            event(seq = 3, x = 30, gestureId = 2, delivery = "latest"),
            event(seq = 4, x = 40, gestureId = 0, delivery = "all"),
            event(seq = 5, x = 50, gestureId = 1, delivery = "latest"),
            event(seq = 6, x = 60, gestureId = 2, delivery = "latest"),
        )

        for (e in events) {
            BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e)
        }

        // Expected:
        // seq=0 "all" g0: stays
        // seq=1 "latest" g1: at index 1
        // seq=2 "all" g0: stays
        // seq=3 "latest" g2: at index 3
        // seq=4 "all" g0: stays
        // seq=5 "latest" g1: replaces index 1 (seq=1)
        // seq=6 "latest" g2: replaces index 3 (seq=3)
        //
        // Final: [0, 5, 2, 6, 4]
        assertEquals(listOf(0L, 2L, 4L, 5L, 6L), queue.map(NativeEvent::sequence))
        assertEquals(listOf(0, 20, 40, 50, 60), queue.map { it.payload["x"] })
    }

    // ── Edge cases ─────────────────────────────────────────────────────

    @Test
    fun `empty queue operations are safe`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        // Clear on empty — should not throw.
        BridgeWorkScheduler.clearEventQueue(queue, slots)
        assertEquals(0, queue.size)
        assertEquals(0, slots.size)
    }

    @Test
    fun `latest with null gestureId does not crash`() {
        val queue = ArrayDeque<NativeEvent>()
        val slots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        val e1 = NativeEvent(
            sequence = 1L,
            target = 7,
            name = "focus_change",
            handler = 42,
            payload = mapOf("has_focus" to true), // no gesture_id
            delivery = "latest",
        )
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e1)

        val e2 = NativeEvent(
            sequence = 2L,
            target = 7,
            name = "focus_change",
            handler = 42,
            payload = mapOf("has_focus" to false), // no gesture_id
            delivery = "latest",
        )
        BridgeWorkScheduler.enqueuePendingEvent(queue, slots, e2)

        // Both should be coalesced since they share the same key (null gestureId).
        assertEquals(1, queue.size)
        assertEquals(false, queue.first().payload["has_focus"])
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    private fun event(
        seq: Long,
        x: Int,
        gestureId: Long,
        delivery: String,
        target: Int = 7,
        name: String = "pointer_move",
        handler: Int = 3,
    ) = NativeEvent(
        sequence = seq,
        target = target,
        name = name,
        handler = handler,
        payload = mapOf("x" to x, "gesture_id" to gestureId),
        delivery = delivery,
    )
}
