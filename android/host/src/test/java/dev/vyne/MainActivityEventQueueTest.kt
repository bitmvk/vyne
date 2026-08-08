package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals

class MainActivityEventQueueTest {
    @Test
    fun idleBridgeBeginsPendingDispatchImmediately() {
        val scheduler = BridgeWorkScheduler<String>()
        scheduler.enqueueEvent(event(1, 10, 1, "all"))
        assertEquals(true, scheduler.next() is BridgeWorkScheduler.Work.Events)
    }

    @Test
    fun inFlightBridgeRetainsPendingWorkForBackpressure() {
        val scheduler = BridgeWorkScheduler<String>()
        scheduler.beginStartup()
        scheduler.enqueueEvent(event(1, 10, 1, "all"))
        assertEquals(null, scheduler.next())
        scheduler.finish()
        assertEquals(true, scheduler.next() is BridgeWorkScheduler.Work.Events)
    }

    @Test
    fun launchWorkUsesTheSameSingleInFlightBoundary() {
        val scheduler = BridgeWorkScheduler<String>()
        scheduler.enqueueLaunch(
            NativeLaunchData(null, null, emptyMap(), sequence = 1),
        )
        assertEquals(true, scheduler.next() is BridgeWorkScheduler.Work.Launch)
    }

    @Test
    fun callbackWorkUsesTheSameSingleInFlightBoundary() {
        val scheduler = BridgeWorkScheduler<String>()
        scheduler.enqueueCallback("callback")
        assertEquals(true, scheduler.next() is BridgeWorkScheduler.Work.Callbacks)
    }

    @Test
    fun latestDeliveryReplacesOnlyTheSameQueuedGestureEvent() {
        val queue = ArrayDeque<NativeEvent>()
        val latestSlots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        val firstMove = event(sequence = 1, x = 10, gestureId = 4, delivery = "latest")
        val ordinary = event(sequence = 2, x = 20, gestureId = 4, delivery = "all")
        val latestMove = event(sequence = 3, x = 30, gestureId = 4, delivery = "latest")
        val nextGesture = event(sequence = 4, x = 40, gestureId = 5, delivery = "latest")

        BridgeWorkScheduler.enqueuePendingEvent(queue, latestSlots, firstMove)
        BridgeWorkScheduler.enqueuePendingEvent(queue, latestSlots, ordinary)
        BridgeWorkScheduler.enqueuePendingEvent(queue, latestSlots, latestMove)
        BridgeWorkScheduler.enqueuePendingEvent(queue, latestSlots, nextGesture)

        // In-place replacement preserves FIFO slot position:
        // firstMove (seq=1) replaced in-place by latestMove (seq=3).
        // ordinary (seq=2) stays at position 1.
        // nextGesture (seq=4) has different gestureId, appended.
        assertEquals(listOf(2L, 3L, 4L), queue.map(NativeEvent::sequence))
        assertEquals(listOf(20, 30, 40), queue.map { it.payload["x"] })
    }

    @Test
    fun clearEventQueueEmptiesBothQueueAndSlots() {
        val queue = ArrayDeque<NativeEvent>()
        val latestSlots = mutableMapOf<BridgeWorkScheduler.LatestKey, Int>()

        BridgeWorkScheduler.enqueuePendingEvent(
            queue, latestSlots,
            event(sequence = 1, x = 10, gestureId = 1, delivery = "latest"),
        )
        assertEquals(1, queue.size)
        assertEquals(1, latestSlots.size)

        BridgeWorkScheduler.clearEventQueue(queue, latestSlots)
        assertEquals(0, queue.size)
        assertEquals(0, latestSlots.size)
    }

    private fun event(
        sequence: Long,
        x: Int,
        gestureId: Long,
        delivery: String,
    ) = NativeEvent(
        sequence = sequence,
        target = 7,
        name = "pointer_move",
        handler = 3,
        payload = mapOf("x" to x, "gesture_id" to gestureId),
        delivery = delivery,
    )
}
