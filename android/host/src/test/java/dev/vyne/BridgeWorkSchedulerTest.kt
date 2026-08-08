package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull

class BridgeWorkSchedulerTest {
    @Test
    fun receiptBeforeLaunchThenQueuedUserEvent() {
        val scheduler = BridgeWorkScheduler<String>()
        val userEvent = event(sequence = 2, name = "press")
        val receipt = event(sequence = 0, name = "__vyne_system__")
        val launch = NativeLaunchData("open", null, emptyMap(), sequence = 3)

        scheduler.enqueueEvent(userEvent)
        scheduler.enqueueReceipt(receipt)
        scheduler.enqueueLaunch(launch)

        val receipts = assertIs<BridgeWorkScheduler.Work.Events>(scheduler.next())
        assertEquals(listOf(receipt), receipts.values)
        assertNull(scheduler.next())

        scheduler.finish()
        assertEquals(launch, assertIs<BridgeWorkScheduler.Work.Launch>(scheduler.next()).value)

        scheduler.finish()
        assertEquals(
            listOf(userEvent),
            assertIs<BridgeWorkScheduler.Work.Events>(scheduler.next()).values,
        )
    }

    @Test
    fun userEventsRunBeforeCallbacksWhenNoLaunchWaits() {
        val scheduler = BridgeWorkScheduler<String>()
        scheduler.enqueueCallback("callback")
        scheduler.enqueueEvent(event(sequence = 1, name = "press"))

        assertIs<BridgeWorkScheduler.Work.Events>(scheduler.next())
        scheduler.finish()
        assertEquals(
            listOf("callback"),
            assertIs<BridgeWorkScheduler.Work.Callbacks<String>>(scheduler.next()).values,
        )
    }

    @Test
    fun applyReceiptPrecedesLifecycleEmittedByAcceptedAnimation() {
        val scheduler = BridgeWorkScheduler<String>()
        val lifecycle =
            NativeEvent(
                sequence = 9,
                target = 1,
                name = "__vyne_system__",
                handler = 0,
                payload =
                    mapOf(
                        "type" to "animation_lifecycle",
                        "animation_id" to 4L,
                        "status" to "completed",
                    ),
                delivery = "ordered",
            )
        val receipt = event(sequence = 0, name = "__vyne_system__")

        // A zero-duration animation can emit lifecycle while the commit is
        // still being accepted. The correlated receipt must reach Python first.
        scheduler.enqueueEvent(lifecycle)
        scheduler.enqueueReceipt(receipt)

        assertEquals(
            listOf(receipt, lifecycle),
            assertIs<BridgeWorkScheduler.Work.Events>(scheduler.next()).values,
        )
    }

    @Test
    fun latestCallbackReplacementIsBoundedAndOrderedByArrival() {
        val scheduler = BridgeWorkScheduler<String>()
        scheduler.enqueueCallback("first", latestKey = 7)
        scheduler.enqueueCallback("ordered")
        scheduler.enqueueCallback("newest", latestKey = 7)

        assertEquals(
            listOf("ordered", "newest"),
            assertIs<BridgeWorkScheduler.Work.Callbacks<String>>(scheduler.next()).values,
        )
    }

    @Test
    fun removingCallbacksRebuildsLatestSlots() {
        val scheduler = BridgeWorkScheduler<String>()
        scheduler.enqueueCallback("remove", latestKey = 1)
        scheduler.enqueueCallback("keep", latestKey = 2)
        scheduler.removeCallbacks { it == "remove" }
        scheduler.enqueueCallback("replacement", latestKey = 2)

        assertEquals(
            listOf("replacement"),
            assertIs<BridgeWorkScheduler.Work.Callbacks<String>>(scheduler.next()).values,
        )
    }

    @Test
    fun clearReleasesBackpressureAndDropsEveryWorkClass() {
        val scheduler = BridgeWorkScheduler<String>()
        scheduler.beginStartup()
        scheduler.enqueueEvent(event(1, "press"))
        scheduler.enqueueReceipt(event(0, "__vyne_system__"))
        scheduler.enqueueLaunch(NativeLaunchData(null, null, emptyMap(), 1))
        scheduler.enqueueCallback("callback")

        scheduler.clear()

        assertEquals(false, scheduler.inFlight)
        assertEquals(false, scheduler.hasPendingWork)
        assertNull(scheduler.next())
    }

    private fun event(sequence: Long, name: String) =
        NativeEvent(
            sequence = sequence,
            target = 1,
            name = name,
            handler = 2,
            payload =
                if (name == "__vyne_system__") {
                    mapOf("type" to "native_apply_result")
                } else {
                    emptyMap()
                },
            delivery = "all",
        )
}
