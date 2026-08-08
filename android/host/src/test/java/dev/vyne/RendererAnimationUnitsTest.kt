package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Unit tests for the unified PresentationEngine physics and the Renderer helpers.
 *
 * The PresentationEngine provides one spring physics implementation used by
 * both View and Canvas adapters.  These tests verify the numerical behaviour.
 */
class RendererAnimationUnitsTest {
    @Test
    fun liveDimensionValuesAreConvertedBackToDp() {
        assertEquals(24f, Renderer.pixelsToDp(72f, 3f))
    }

    @Test
    fun invalidDensityLeavesTheValueUnchanged() {
        assertEquals(24f, Renderer.pixelsToDp(24f, 0f))
    }

    @Test
    fun outsideTapDetectionDistinguishesTapJitterFromScrolling() {
        assertEquals(false, Renderer.movedBeyondTapSlop(3f, 4f, 8f))
        assertEquals(true, Renderer.movedBeyondTapSlop(8f, 8f, 8f))
    }

    @Test
    fun pointerPayloadUsesDensityIndependentLocalCoordinates() {
        assertEquals(
            linkedMapOf(
                "x" to 24f,
                "y" to 12f,
                "down_x" to 8f,
                "down_y" to 4f,
                "pointer_id" to 3,
                "gesture_id" to 11L,
            ),
            Renderer.pointerPayload(72f, 36f, 24f, 12f, 3f, 3, 11L),
        )
    }

    @Test
    fun pointerAxisWaitsForSlopThenChoosesTheDominantDirection() {
        assertEquals(null, Renderer.resolvePointerAxis(3f, 4f, 8f))
        assertEquals("horizontal", Renderer.resolvePointerAxis(12f, 3f, 8f))
        assertEquals("vertical", Renderer.resolvePointerAxis(3f, 12f, 8f))
    }

    // ── Unified spring physics (PresentationEngine) ────────────────

    @Test
    fun isolatedTargetsUseTheirDeclaredDuration() {
        assertEquals(48L, PresentationEngine.effectiveRetargetDuration(48L, null, 11L))
        assertEquals(48L, PresentationEngine.effectiveRetargetDuration(48L, 60L, 11L))
    }

    @Test
    fun streamingTargetsAdaptToTheObservedCadence() {
        assertEquals(11L, PresentationEngine.effectiveRetargetDuration(48L, 11L, 11L))
        assertEquals(11L, PresentationEngine.effectiveRetargetDuration(48L, 5L, 11L))
        assertEquals(22L, PresentationEngine.effectiveRetargetDuration(48L, 22L, 11L))
        assertEquals(0L, PresentationEngine.effectiveRetargetDuration(0L, 5L, 11L))
    }

    @Test
    fun velocityPreservingTweenMatchesBothBoundaryConditions() {
        val duration = 100_000_000L
        val start =
            PresentationEngine.velocityPreservingTween(
                start = 4f,
                target = 20f,
                initialVelocity = 100f,
                terminalVelocity = 200f,
                durationNanos = duration,
                rawFraction = 0f,
            )
        val end =
            PresentationEngine.velocityPreservingTween(
                start = 4f,
                target = 20f,
                initialVelocity = 100f,
                terminalVelocity = 200f,
                durationNanos = duration,
                rawFraction = 1f,
            )

        assertEquals(4f, start.first, 0.001f)
        assertEquals(100f, start.second, 0.001f)
        assertEquals(20f, end.first, 0.001f)
        assertEquals(200f, end.second, 0.001f)
    }

    @Test
    fun extremeVelocitiesCannotOvershootTheTarget() {
        val duration = 48_000_000L
        for (step in 0..100) {
            val sample =
                PresentationEngine.velocityPreservingTween(
                    start = 0f,
                    target = 1f,
                    initialVelocity = 100_000f,
                    terminalVelocity = 100_000f,
                    durationNanos = duration,
                    rawFraction = step / 100f,
                )
            assertTrue(sample.first in 0f..1f)
            assertTrue(sample.second >= -0.001f)
        }
    }

    @Test
    fun fastDirectionReversalCannotContinuePastTheOldPosition() {
        val duration = 48_000_000L
        for (step in 0..100) {
            val sample =
                PresentationEngine.velocityPreservingTween(
                    start = 1f,
                    target = 0f,
                    initialVelocity = 100_000f,
                    terminalVelocity = -100_000f,
                    durationNanos = duration,
                    rawFraction = step / 100f,
                )
            assertTrue(sample.first in 0f..1f)
            assertTrue(sample.second <= 0.001f)
        }
    }

    @Test
    fun easingDerivativesMatchLinearAndEaseOutEndpoints() {
        assertEquals(1f, PresentationEngine.easingDerivative("linear", 0.5f))
        assertEquals(2f, PresentationEngine.easingDerivative("ease_out", 0f))
        assertEquals(0f, PresentationEngine.easingDerivative("ease_out", 1f))
    }

    @Test
    fun springMovesAndSettlesAtItsTarget() {
        val first = PresentationEngine.springStep(
            value = 0f,
            target = 1f,
            velocity = 0f,
            elapsedSeconds = 1f / 60f,
            dampingRatio = 0.6f,
            stiffness = 800f,
        )

        assertTrue(first.first > 0f)
        assertTrue(first.second > 0f)
        assertFalse(
            PresentationEngine.springAtRest(
                first.first, 1f, first.second, 0.01f, 0.01f,
            )
        )
        assertTrue(
            PresentationEngine.springAtRest(1f, 1f, 0f, 0.01f, 0.01f)
        )
    }

    @Test
    fun springAtRestRespectsCustomThresholds() {
        // Very close but not quite at target: not at rest with tight thresholds.
        assertFalse(
            PresentationEngine.springAtRest(0.999f, 1f, 0.0005f, 0.0001f, 0.0001f)
        )
        // Same values with loose thresholds: at rest.
        assertTrue(
            PresentationEngine.springAtRest(0.999f, 1f, 0.0005f, 0.01f, 0.01f)
        )
    }

    @Test
    fun springWithVelocityContinuesMoving() {
        val step = PresentationEngine.springStep(
            value = 0f,
            target = 1f,
            velocity = 5f, // Large initial velocity
            elapsedSeconds = 1f / 60f,
            dampingRatio = 0.6f,
            stiffness = 800f,
        )
        // Should overshoot because of high velocity.
        assertTrue(step.first > 0f, "Should move forward despite velocity")
    }

    @Test
    fun criticallyDampedSpringDoesNotOscillate() {
        // Damping ratio = 1.0 means critically damped.
        val step = PresentationEngine.springStep(
            value = 0f,
            target = 1f,
            velocity = 0f,
            elapsedSeconds = 1f / 30f,
            dampingRatio = 1.0f,
            stiffness = 100f,
        )
        assertTrue(step.first > 0f)
        assertTrue(step.first <= 1f, "Critically damped should not overshoot")
    }
}
