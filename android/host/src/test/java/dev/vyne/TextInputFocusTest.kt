/**
 * Tests for TextInput focus, IME, controlled text, and accessibility semantics.
 * Part of INPUT-09 acceptance criteria.
 *
 * These are pure JVM unit tests that verify state transitions, property
 * tracking, and decision logic without requiring an Android device.
 */
package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class TextInputFocusTest {

    // ── ViewState tracking ────────────────────────────────────────────

    @Test
    fun `blurOnTapOutside is tracked in view state`() {
        val state = Renderer.ViewState()
        state.blurOnTapOutside = true
        assertTrue(state.blurOnTapOutside)
        state.blurOnTapOutside = false
        assertFalse(state.blurOnTapOutside)
    }

    @Test
    fun `blurOnKeyboardHide is tracked in view state`() {
        val state = Renderer.ViewState()
        state.blurOnKeyboardHide = true
        assertTrue(state.blurOnKeyboardHide)
    }

    @Test
    fun `blurOnSubmit is tracked in view state`() {
        val state = Renderer.ViewState()
        state.blurOnSubmit = true
        assertTrue(state.blurOnSubmit)
    }

    @Test
    fun `editorActionHandler is tracked in view state`() {
        val state = Renderer.ViewState()
        state.editorActionHandler = 42
        assertEquals(42, state.editorActionHandler)
        state.editorActionHandler = null
        assertEquals(null, state.editorActionHandler)
    }

    @Test
    fun `controlledFocus is tracked in view state`() {
        val state = Renderer.ViewState()
        state.controlledFocus = true
        assertEquals(true, state.controlledFocus)
    }

    @Test
    fun `pointer handlers are stored per view state`() {
        val state = Renderer.ViewState()
        assertTrue(state.pointerHandlers.isEmpty())
        state.pointerHandlers["pointer_down"] = 1
        assertEquals(1, state.pointerHandlers["pointer_down"])
        assertTrue("pointer_down" in state.pointerHandlers)
    }

    @Test
    fun `pointerSession defaults to IDLE`() {
        val state = Renderer.ViewState()
        assertEquals(PointerPhase.Idle, state.pointerSession.phase)
        assertEquals(null, state.pointerSession.activePointerId)
    }

    @Test
    fun `pointerCaptureAxis is nullable and defaults to null`() {
        val state = Renderer.ViewState()
        assertEquals(null, state.pointerCaptureAxis)
        state.pointerCaptureAxis = "horizontal"
        assertEquals("horizontal", state.pointerCaptureAxis)
        state.pointerCaptureAxis = null
        assertEquals(null, state.pointerCaptureAxis)
    }

    // ── Accessibility state tracking ──────────────────────────────────

    @Test
    fun `accessibilityRole is tracked in view state`() {
        val state = Renderer.ViewState()
        assertEquals(null, state.accessibilityRole)
        state.accessibilityRole = "button"
        assertEquals("button", state.accessibilityRole)
        state.accessibilityRole = null
        assertEquals(null, state.accessibilityRole)
    }

    @Test
    fun `accessibilityStateSelected is tracked in view state`() {
        val state = Renderer.ViewState()
        assertFalse(state.accessibilityStateSelected)
        state.accessibilityStateSelected = true
        assertTrue(state.accessibilityStateSelected)
    }

    @Test
    fun `accessibilityStateChecked supports checked, unchecked, and mixed`() {
        val state = Renderer.ViewState()
        assertEquals(null, state.accessibilityStateChecked)
        state.accessibilityStateChecked = "checked"
        assertEquals("checked", state.accessibilityStateChecked)
        state.accessibilityStateChecked = "unchecked"
        assertEquals("unchecked", state.accessibilityStateChecked)
        state.accessibilityStateChecked = "mixed"
        assertEquals("mixed", state.accessibilityStateChecked)
    }

    @Test
    fun `accessibilityStateDescription is tracked in view state`() {
        val state = Renderer.ViewState()
        assertEquals(null, state.accessibilityStateDescription)
        state.accessibilityStateDescription = "Volume: 50%"
        assertEquals("Volume: 50%", state.accessibilityStateDescription)
    }

    @Test
    fun `accessibilityRange values are tracked in view state`() {
        val state = Renderer.ViewState()
        assertEquals(0f, state.accessibilityRangeMin)
        assertEquals(0f, state.accessibilityRangeMax)
        assertEquals(0f, state.accessibilityRangeCurrent)

        state.accessibilityRangeMin = 0f
        state.accessibilityRangeMax = 100f
        state.accessibilityRangeCurrent = 50f

        assertEquals(0f, state.accessibilityRangeMin)
        assertEquals(100f, state.accessibilityRangeMax)
        assertEquals(50f, state.accessibilityRangeCurrent)
    }

    // ── Dimension constraints ─────────────────────────────────────────

    @Test
    fun `max constraints cap mechanical measured dimensions`() {
        val constrained = object : MaxConstrainedView {
            override var vyneMaxWidthPx = 200
            override var vyneMaxHeightPx = 400
        }
        assertEquals(200 to 400, constrained.constrainMeasured(800, 600))
        constrained.vyneMaxWidthPx = 0
        constrained.vyneMaxHeightPx = 0
        assertEquals(800 to 600, constrained.constrainMeasured(800, 600))
    }

    // ── POINTER_EVENTS constant ───────────────────────────────────────

    @Test
    fun `POINTER_EVENTS includes all four pointer event names`() {
        assertEquals(
            setOf("pointer_cancel", "pointer_down", "pointer_move", "pointer_up"),
            Renderer.POINTER_EVENTS
        )
    }

    // ── ApplyResult enum ──────────────────────────────────────────────

    @Test
    fun `ApplyResult has four defined values`() {
        assertEquals(4, Renderer.ApplyResult.entries.size)
    }

    // ── Dimension utilities ───────────────────────────────────────────

    @Test
    fun `pixelsToDp converts correctly`() {
        val dp = Renderer.pixelsToDp(48f, 3f)
        assertEquals(16f, dp)
    }

    @Test
    fun `pixelsToDp handles zero density safely`() {
        val dp = Renderer.pixelsToDp(48f, 0f)
        assertEquals(48f, dp) // returns pixels when density is zero
    }

    @Test
    fun `resolvePointerAxis returns null within slop`() {
        assertEquals(null, Renderer.resolvePointerAxis(3f, 4f, 8f))
    }

    @Test
    fun `resolvePointerAxis detects horizontal swipe`() {
        assertEquals("horizontal", Renderer.resolvePointerAxis(12f, 3f, 8f))
    }

    @Test
    fun `resolvePointerAxis detects vertical swipe`() {
        assertEquals("vertical", Renderer.resolvePointerAxis(3f, 12f, 8f))
    }

    @Test
    fun `movedBeyondTapSlop detects movement`() {
        assertTrue(Renderer.movedBeyondTapSlop(10f, 0f, 8f))
        assertFalse(Renderer.movedBeyondTapSlop(5f, 5f, 8f))
    }

    // ── Pointer payload building ──────────────────────────────────────

    @Test
    fun `pointerPayload returns dp-converted coordinates`() {
        val payload = Renderer.pointerPayload(
            xPixels = 96f, yPixels = 192f,
            downXPixels = 48f, downYPixels = 96f,
            density = 3f,
            pointerId = 7, gestureId = 42L,
        )
        assertEquals(32f, payload["x"])     // 96/3
        assertEquals(64f, payload["y"])     // 192/3
        assertEquals(16f, payload["down_x"]) // 48/3
        assertEquals(32f, payload["down_y"]) // 96/3
        assertEquals(7, payload["pointer_id"])
        assertEquals(42L, payload["gesture_id"])
    }
}
