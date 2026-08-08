package dev.vyne

import android.view.MotionEvent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class PointerSessionTest {

    // ── Axis resolution ─────────────────────────────────────────

    @Test
    fun axisResolutionWaitsForSlop() {
        assertEquals(null, PointerSession.resolveAxis(3f, 4f, 8f))
    }

    @Test
    fun axisResolutionChoosesDominantDirection() {
        assertEquals("horizontal", PointerSession.resolveAxis(12f, 3f, 8f))
        assertEquals("vertical", PointerSession.resolveAxis(3f, 12f, 8f))
    }

    // ── Down transitions ─────────────────────────────────────────

    @Test
    fun downWithoutAxisCaptureTransitionsToCapturedAndEmitsDown() {
        val event = pointerEvent(
            action = MotionEvent.ACTION_DOWN,
            pointerId = 0, x = 100f, y = 200f,
        )
        val config = testConfig(captureAxis = null, hasPointerDown = true)
        val transition = PointerSession.reduce(PointerSessionState.IDLE, event, config)

        assertEquals(PointerPhase.Captured, transition.state.phase)
        assertEquals(0, transition.state.activePointerId)
        assertEquals(100f, transition.state.downX)
        assertEquals(200f, transition.state.downY)
        assertEquals(100f, transition.state.lastX)
        assertEquals(200f, transition.state.lastY)
        assertTrue(transition.state.downEmitted)
        assertTrue(transition.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_down" })
        assertFalse(transition.decisions.any { it is PointerDecision.ParentIntercept })
    }

    @Test
    fun downWithAxisCaptureTransitionsToPendingAxisWithoutEmittingDown() {
        val event = pointerEvent(
            action = MotionEvent.ACTION_DOWN,
            pointerId = 0, x = 100f, y = 200f,
        )
        val config = testConfig(captureAxis = "horizontal", hasPointerDown = true)
        val transition = PointerSession.reduce(PointerSessionState.IDLE, event, config)

        assertEquals(PointerPhase.PendingAxis, transition.state.phase)
        assertEquals(0, transition.state.activePointerId)
        assertEquals(null, transition.state.axisClaimed)
        assertFalse(transition.state.downEmitted)
        assertTrue(transition.decisions.any { it is PointerDecision.ParentIntercept && it.disallow })
    }

    @Test
    fun downPreservesOriginalPayload() {
        val event = pointerEvent(
            action = MotionEvent.ACTION_DOWN,
            pointerId = 1, x = 50f, y = 75f,
            downTime = 1000L, eventTime = 1001L,
            pressure = 0.8f, size = 0.2f,
        )
        val config = testConfig(captureAxis = null, hasPointerDown = true)
        val transition = PointerSession.reduce(PointerSessionState.IDLE, event, config)

        assertEquals(1, transition.state.activePointerId)
        assertEquals(1000L, transition.state.downTime)
        assertEquals(1001L, transition.state.downEventTime)
        assertEquals(0.8f, transition.state.downPressure)
        assertEquals(0.2f, transition.state.downSize)
    }

    // ── Pending axis → Captured ──────────────────────────────────

    @Test
    fun pendingAxisMovesBeyondSlopAndCapturesWhenDirectionMatches() {
        val config = testConfig(captureAxis = "horizontal", hasPointerDown = true, hasPointerMove = true)
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        val moveResult = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_MOVE, pointerId = 0, x = 130f, y = 205f),
            config,
        )

        assertEquals(PointerPhase.Captured, moveResult.state.phase)
        assertEquals(true, moveResult.state.axisClaimed)
        assertTrue(moveResult.decisions.any { it is PointerDecision.ParentIntercept && it.disallow })
        assertTrue(moveResult.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_down" })
        assertTrue(moveResult.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_move" })
    }

    @Test
    fun pendingAxisMovesBeyondSlopAndRejectsWhenDirectionDoesNotMatch() {
        val config = testConfig(
            captureAxis = "horizontal",
            hasPointerDown = true, hasPointerMove = true, hasPointerCancel = true,
        )
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        val moveResult = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_MOVE, pointerId = 0, x = 105f, y = 230f),
            config,
        )

        assertEquals(PointerPhase.Rejected, moveResult.state.phase)
        assertEquals(false, moveResult.state.axisClaimed)
        assertTrue(moveResult.decisions.any { it is PointerDecision.ParentIntercept && !it.disallow })
        assertTrue(moveResult.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_cancel" })
    }

    // ── Tap qualification ────────────────────────────────────────

    @Test
    fun upWithoutAxisCaptureQualifiesAsTapAndEmitsPerformClick() {
        val config = testConfig(captureAxis = null, hasPointerDown = true, hasPointerUp = true)
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        val upResult = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_UP, pointerId = 0, x = 102f, y = 201f),
            config,
        )

        assertEquals(PointerPhase.Ended, upResult.state.phase)
        assertTrue(upResult.decisions.any { it is PointerDecision.PerformClick })
        assertTrue(upResult.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_up" })
        assertTrue(upResult.decisions.any { it is PointerDecision.Reset })
    }

    @Test
    fun upWithinPendingAxisQualifiesAsTapWithLateDown() {
        val config = testConfig(
            captureAxis = "horizontal",
            hasPointerDown = true, hasPointerUp = true,
        )
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        // Up without moving beyond slop — qualifies as tap.
        val upResult = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_UP, pointerId = 0, x = 105f, y = 205f),
            config,
        )

        assertEquals(PointerPhase.Ended, upResult.state.phase)
        assertTrue(upResult.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_down" })
        assertTrue(upResult.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_up" })
        assertTrue(upResult.decisions.any { it is PointerDecision.PerformClick })
    }

    @Test
    fun capturedMoveBeyondSlopDoesNotQualifyAsTap() {
        val config = testConfig(captureAxis = null, hasPointerDown = true, hasPointerMove = true, hasPointerUp = true)
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        val moveResult = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_MOVE, pointerId = 0, x = 150f, y = 250f),
            config,
        )

        val upResult = PointerSession.reduce(
            moveResult.state,
            pointerEvent(action = MotionEvent.ACTION_UP, pointerId = 0, x = 150f, y = 250f),
            config,
        )

        // Moved beyond slop in captured phase → no tap.
        assertFalse(upResult.decisions.any { it is PointerDecision.PerformClick })
    }

    // ── Cancel ───────────────────────────────────────────────────

    @Test
    fun cancelEmitsPointerCancelAndResets() {
        val config = testConfig(captureAxis = null, hasPointerDown = true, hasPointerCancel = true)
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        val cancelResult = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_CANCEL, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        assertEquals(PointerPhase.Cancelled, cancelResult.state.phase)
        assertTrue(cancelResult.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_cancel" })
        assertTrue(cancelResult.decisions.any { it is PointerDecision.Reset })
        assertTrue(cancelResult.decisions.any { it is PointerDecision.ParentIntercept && !it.disallow })
    }

    @Test
    fun cancelInPendingAxisEmitsCancel() {
        val config = testConfig(captureAxis = "horizontal", hasPointerDown = true, hasPointerCancel = true)
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        val cancelResult = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_CANCEL, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        assertEquals(PointerPhase.Cancelled, cancelResult.state.phase)
        assertTrue(cancelResult.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_cancel" })
    }

    // ── Pointer up ───────────────────────────────────────────────

    @Test
    fun pointerUpOnActivePointerEndsGesture() {
        val config = testConfig(captureAxis = null, hasPointerDown = true, hasPointerUp = true)
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        val result = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_POINTER_UP, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        assertTrue(result.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_up" })
        assertTrue(result.decisions.any { it is PointerDecision.Reset })
    }

    @Test
    fun pointerUpOnNonActivePointerIsNoop() {
        val config = testConfig(captureAxis = null, hasPointerDown = true, hasPointerUp = true)
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        val result = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_POINTER_UP, pointerId = 1, x = 300f, y = 400f),
            config,
        )

        assertFalse(result.decisions.any { it !is PointerDecision.Noop })
    }

    // ── Additional pointer down ──────────────────────────────────

    @Test
    fun additionalPointerDownCancelsAndSuppressesGesture() {
        val config = testConfig(
            captureAxis = null, hasPointerDown = true, hasPointerCancel = true,
        )
        val downResult = PointerSession.reduce(
            PointerSessionState.IDLE,
            pointerEvent(action = MotionEvent.ACTION_DOWN, pointerId = 0, x = 100f, y = 200f),
            config,
        )

        val result = PointerSession.reduce(
            downResult.state,
            pointerEvent(action = MotionEvent.ACTION_POINTER_DOWN, pointerId = 1, x = 300f, y = 400f),
            config,
        )

        assertEquals(PointerPhase.Suppressed, result.state.phase)
        assertTrue(result.decisions.any { it is PointerDecision.EmitPointerEvent && it.eventName == "pointer_cancel" })
        assertTrue(result.decisions.any { it == PointerDecision.ParentIntercept(false) })
    }

    // ── Idle ignores non-down events ─────────────────────────────

    @Test
    fun moveWhileIdleIsNoop() {
        val event = pointerEvent(action = MotionEvent.ACTION_MOVE, pointerId = 0, x = 10f, y = 20f)
        val transition = PointerSession.reduce(PointerSessionState.IDLE, event, testConfig())
        assertEquals(PointerPhase.Idle, transition.state.phase)
        assertFalse(transition.decisions.any { it !is PointerDecision.Noop })
    }

    @Test
    fun upWhileIdleIsNoop() {
        val event = pointerEvent(action = MotionEvent.ACTION_UP, pointerId = 0, x = 10f, y = 20f)
        val transition = PointerSession.reduce(PointerSessionState.IDLE, event, testConfig())
        assertEquals(PointerPhase.Idle, transition.state.phase)
    }

    // ── Helpers ──────────────────────────────────────────────────

    private fun pointerEvent(
        action: Int,
        pointerId: Int,
        x: Float,
        y: Float,
        actionIndex: Int = 0,
        pointerCount: Int = 1,
        downTime: Long = 0L,
        eventTime: Long = 0L,
        pressure: Float = 1f,
        size: Float = 0f,
    ) = PointerEvent(
        action = action,
        pointerId = pointerId,
        actionIndex = actionIndex,
        pointerCount = pointerCount,
        x = x,
        y = y,
        rawX = x,
        rawY = y,
        downTime = downTime,
        eventTime = eventTime,
        pressure = pressure,
        size = size,
        toolType = MotionEvent.TOOL_TYPE_FINGER,
        source = 0,
    )

    private fun testConfig(
        captureAxis: String? = null,
        hasPointerDown: Boolean = false,
        hasPointerMove: Boolean = false,
        hasPointerUp: Boolean = false,
        hasPointerCancel: Boolean = false,
    ) = PointerSessionConfig(
        touchSlop = 8f,
        captureAxis = captureAxis,
        hasPointerDown = hasPointerDown,
        hasPointerMove = hasPointerMove,
        hasPointerUp = hasPointerUp,
        hasPointerCancel = hasPointerCancel,
        gestureId = 42L,
    )
}
