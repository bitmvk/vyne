package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

private class FakeAnimationFrameClock : AnimationFrameClock {
    override val frameIntervalMillis: Long = 16L
    var nowNanos: Long = 0L
    private var callback: ((Long) -> Unit)? = null

    override fun postFrame(callback: (Long) -> Unit) {
        check(this.callback == null) { "Only one frame may be scheduled" }
        this.callback = callback
    }

    override fun cancelFrame() {
        callback = null
    }

    fun advanceTo(milliseconds: Long) {
        nowNanos = milliseconds * 1_000_000L
        val pending = callback
        callback = null
        requireNotNull(pending) { "No frame was scheduled" }(nowNanos)
    }

    fun hasFrame(): Boolean = callback != null
}

private class FloatAdapter(initial: Float) : PresentationEngine.PropertyAdapter {
    var value = initial
    override fun read(): Float = value
    override fun write(value: Float) {
        this.value = value
    }
}

class PresentationEngineTest {
    private data class Fixture(
        val engine: PresentationEngine,
        val clock: FakeAnimationFrameClock,
        val adapter: FloatAdapter,
        val lifecycle: MutableList<PresentationEngine.Lifecycle>,
    )

    private fun fixture(initial: Float = 0f): Fixture {
        val clock = FakeAnimationFrameClock()
        val lifecycle = mutableListOf<PresentationEngine.Lifecycle>()
        val engine =
            PresentationEngine(
                frameClock = clock,
                nowNanos = { clock.nowNanos },
                lifecycleSink = lifecycle::add,
            )
        val adapter = FloatAdapter(initial)
        engine.registerAdapter("view:1:prop:opacity", adapter)
        return Fixture(engine, clock, adapter, lifecycle)
    }

    private fun Fixture.start(
        id: Long = 1L,
        targets: List<Float> = listOf(1f),
        duration: Long = 100L,
        from: Float? = null,
        retarget: String = "restart",
        spec: String = "tween",
    ) {
        engine.setTarget(
            animationId = id,
            slotKey = "view:1:prop:opacity",
            nodeId = 1,
            property = "opacity",
            spec = spec,
            targets = targets,
            fromValue = from,
            durationMs = duration,
            easing = "linear",
            dampingRatio = 0.8f,
            stiffness = 380f,
            restValueThreshold = 0.01f,
            restVelocityThreshold = 0.01f,
            retargetPolicy = retarget,
        )
    }

    @Test
    fun tweenAdvancesEntirelyFromNativeFrameClock() {
        val fixture = fixture()
        fixture.start(targets = listOf(10f))

        assertEquals(0f, fixture.adapter.value)
        fixture.clock.advanceTo(50)
        assertEquals(5f, fixture.adapter.value, 0.001f)
        fixture.clock.advanceTo(100)

        assertEquals(10f, fixture.adapter.value)
        assertFalse(fixture.clock.hasFrame())
        assertEquals("completed", fixture.lifecycle.single().status)
    }

    @Test
    fun keyframesRunSequentiallyAsOneTimeline() {
        val fixture = fixture()
        fixture.start(targets = listOf(10f, 20f))

        fixture.clock.advanceTo(100)
        assertEquals(10f, fixture.adapter.value)
        assertTrue(fixture.engine.hasActiveTransition("view:1:prop:opacity"))
        fixture.clock.advanceTo(150)
        assertEquals(15f, fixture.adapter.value, 0.001f)
        fixture.clock.advanceTo(200)

        assertEquals(20f, fixture.adapter.value)
        assertEquals(1, fixture.lifecycle.size)
        assertEquals("completed", fixture.lifecycle.single().status)
    }

    @Test
    fun springIntegratesAcrossFramesAndSettlesExactlyAtTarget() {
        val fixture = fixture()
        fixture.start(targets = listOf(1f), spec = "spring")

        var elapsed = 0L
        while (fixture.clock.hasFrame() && elapsed < 5_000L) {
            elapsed += 16L
            fixture.clock.advanceTo(elapsed)
        }

        assertFalse(fixture.clock.hasFrame())
        assertTrue(elapsed < 5_000L)
        assertEquals(1f, fixture.adapter.value)
        assertEquals("completed", fixture.lifecycle.single().status)
    }

    @Test
    fun delayedRetargetStartsAtCurrentlyVisibleValue() {
        val fixture = fixture()
        fixture.start(id = 1, targets = listOf(10f))
        fixture.clock.advanceTo(50)
        assertEquals(5f, fixture.adapter.value, 0.001f)

        fixture.start(id = 2, targets = listOf(0f))
        assertEquals("cancelled", fixture.lifecycle.single().status)
        assertEquals("replaced", fixture.lifecycle.single().reason)
        fixture.clock.advanceTo(75)
        assertEquals(2.5f, fixture.adapter.value, 0.001f)
        fixture.clock.advanceTo(100)
        assertEquals(0f, fixture.adapter.value)
    }

    @Test
    fun tweenRetargetCarriesItsCurrentVelocityWithoutAPositionJump() {
        val fixture = fixture()
        fixture.start(id = 1, targets = listOf(10f))
        fixture.clock.advanceTo(40)
        assertEquals(4f, fixture.adapter.value, 0.001f)

        fixture.start(
            id = 2,
            targets = listOf(20f),
            retarget = "maintain_velocity",
        )
        assertEquals(4f, fixture.adapter.value, 0.001f)

        // The old tween was moving at 100 units/s and incoming targets are
        // moving at 250 units/s. Both derivatives shape the replacement
        // without changing its current position.
        fixture.clock.advanceTo(50)
        assertEquals(5.180f, fixture.adapter.value, 0.001f)
        fixture.clock.advanceTo(140)
        assertEquals(20f, fixture.adapter.value, 0.001f)
    }

    @Test
    fun staleGenerationCannotCancelReplacement() {
        val fixture = fixture()
        fixture.start(id = 1, targets = listOf(10f))
        fixture.start(id = 2, targets = listOf(20f))

        assertFalse(
            fixture.engine.cancel(
                "view:1:prop:opacity",
                animationId = 1,
            ),
        )
        assertTrue(fixture.engine.hasActiveTransition("view:1:prop:opacity"))
        assertTrue(
            fixture.engine.cancel(
                "view:1:prop:opacity",
                animationId = 2,
            ),
        )
        assertFalse(fixture.engine.hasActiveTransition("view:1:prop:opacity"))
    }

    @Test
    fun zeroDurationSettlesAndReportsCompletionWithoutFrame() {
        val fixture = fixture()
        fixture.start(targets = listOf(3f), duration = 0)

        assertEquals(3f, fixture.adapter.value)
        assertEquals("completed", fixture.lifecycle.single().status)
        assertFalse(fixture.clock.hasFrame())
    }

    @Test
    fun ignoredRetargetReportsIncomingCancellationAndKeepsCurrentAnimation() {
        val fixture = fixture()
        fixture.start(id = 1, targets = listOf(10f))
        fixture.start(id = 2, targets = listOf(20f), retarget = "ignore")

        assertEquals(2L, fixture.lifecycle.single().animationId)
        assertEquals("ignored", fixture.lifecycle.single().reason)
        fixture.clock.advanceTo(100)
        assertEquals(10f, fixture.adapter.value)
        assertEquals("completed", fixture.lifecycle.last().status)
        assertEquals(1L, fixture.lifecycle.last().animationId)
    }

    @Test
    fun declarativePrimeSnapsFirstTargetAndDoesNotPublishLifecycle() {
        val fixture = fixture(initial = 4f)
        fixture.engine.prime("view:1:prop:opacity", 4f)

        assertFalse(fixture.clock.hasFrame())
        assertEquals(emptyList(), fixture.lifecycle)
        fixture.clock.nowNanos = 200_000_000L
        fixture.start(id = 0, targets = listOf(8f))
        fixture.clock.advanceTo(250)
        assertEquals(6f, fixture.adapter.value, 0.001f)
        fixture.clock.advanceTo(300)
        assertEquals(8f, fixture.adapter.value)
        assertEquals(emptyList(), fixture.lifecycle)
    }

    @Test
    fun disposalCancelsActiveLifecycleAndRemovesScheduledFrame() {
        val fixture = fixture()
        fixture.start(id = 9, targets = listOf(10f))
        fixture.engine.dispose()

        assertFalse(fixture.clock.hasFrame())
        assertEquals("cancelled", fixture.lifecycle.single().status)
        assertEquals("disposed", fixture.lifecycle.single().reason)
    }

    @Test
    fun nodeRemovalCancelsEverySlotForThatNode() {
        val fixture = fixture()
        fixture.start(id = 6, targets = listOf(10f))

        fixture.engine.unregisterNode(1)

        assertFalse(fixture.clock.hasFrame())
        assertFalse(fixture.engine.hasSlot("view:1:prop:opacity"))
        assertEquals("node_removed", fixture.lifecycle.single().reason)
    }

    @Test
    fun adapterFailureCancelsTimelineWithoutCrashingFrameClock() {
        val clock = FakeAnimationFrameClock()
        val lifecycle = mutableListOf<PresentationEngine.Lifecycle>()
        val engine =
            PresentationEngine(
                frameClock = clock,
                nowNanos = { clock.nowNanos },
                lifecycleSink = lifecycle::add,
            )
        engine.registerAdapter(
            "view:1:prop:opacity",
            object : PresentationEngine.PropertyAdapter {
                override fun read(): Float = 0f
                override fun write(value: Float) {
                    error("detached")
                }
            },
        )
        engine.setTarget(
            animationId = 8,
            slotKey = "view:1:prop:opacity",
            nodeId = 1,
            property = "opacity",
            spec = "tween",
            targets = listOf(1f),
            fromValue = null,
            durationMs = 100,
            easing = "linear",
            dampingRatio = 0.8f,
            stiffness = 380f,
            restValueThreshold = 0.01f,
            restVelocityThreshold = 0.01f,
            retargetPolicy = "restart",
        )

        clock.advanceTo(50)

        assertFalse(clock.hasFrame())
        assertEquals("cancelled", lifecycle.single().status)
        assertEquals("adapter_error", lifecycle.single().reason)
    }
}
