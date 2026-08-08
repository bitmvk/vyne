package dev.vyne

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class CallbackAdmissionTest {
    @Test
    fun samplingUsesThePythonSelectedMonotonicInterval() {
        var now = 100L
        val admission =
                CallbackAdmission(
                        delivery = "all",
                        sampleIntervalMs = 50L,
                        clockMs = { now },
                )

        assertEquals(true, admission.accept())
        now = 149L
        assertEquals(false, admission.accept())
        now = 150L
        assertEquals(true, admission.accept())
    }

    @Test
    fun concurrentSamplingAdmitsOnlyOneCallerPerInterval() {
        val admission =
                CallbackAdmission(
                        delivery = "latest",
                        sampleIntervalMs = 10L,
                        clockMs = { 500L },
                )
        val executor = Executors.newFixedThreadPool(8)
        val start = CountDownLatch(1)
        val admitted = AtomicInteger()

        repeat(32) {
            executor.execute {
                start.await()
                if (admission.accept()) admitted.incrementAndGet()
            }
        }
        start.countDown()
        executor.shutdown()

        assertEquals(true, executor.awaitTermination(2, TimeUnit.SECONDS))
        assertEquals(1, admitted.get())
    }

    @Test
    fun invalidNativePolicyIsRejectedDefensively() {
        assertFailsWith<IllegalArgumentException> {
            CallbackAdmission("newest", 0L) { 0L }
        }
        assertFailsWith<IllegalArgumentException> {
            CallbackAdmission("all", -1L) { 0L }
        }
    }

    @Test
    fun latestQueueReplacementStaysBoundedPerSubscription() {
        val queue = ArrayDeque<String>()
        val slots = mutableMapOf<Long, Int>()

        BridgeWorkScheduler.enqueueLatestWork(queue, slots, 1L, "first")
        queue.add("ordered")
        BridgeWorkScheduler.enqueueLatestWork(queue, slots, 1L, "newest")
        BridgeWorkScheduler.enqueueLatestWork(queue, slots, 2L, "other")

        assertEquals(listOf("ordered", "newest", "other"), queue.toList())
        assertEquals(mapOf(1L to 1, 2L to 2), slots)
    }
}
