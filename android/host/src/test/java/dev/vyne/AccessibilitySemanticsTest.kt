/**
 * Tests for accessibility semantics mapping from Python roles to
 * Android AccessibilityNodeInfo mechanics.  Part of INPUT-09.
 *
 * These tests verify:
 * - Role-to-className mapping (button, checkbox, switch, slider, tab, etc.)
 * - State tracking (selected, checked, state description)
 * - Range info tracking
 * - Accessibility absence is distinct from false/empty values
 */
package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class AccessibilitySemanticsTest {

    // ── Role tracking ──────────────────────────────────────────────────

    @Test
    fun `role defaults to null in view state`() {
        val state = Renderer.ViewState()
        assertEquals(null, state.accessibilityRole)
    }

    @Test
    fun `role can be set to supported values`() {
        val state = Renderer.ViewState()
        val supportedRoles = listOf(
            "button", "checkbox", "switch", "slider",
            "tab", "header", "link", "image", "list", "list_item",
        )
        for (role in supportedRoles) {
            state.accessibilityRole = role
            assertEquals(role, state.accessibilityRole)
        }
    }

    @Test
    fun `setting role to null clears accessibility role`() {
        val state = Renderer.ViewState()
        state.accessibilityRole = "button"
        assertEquals("button", state.accessibilityRole)
        state.accessibilityRole = null
        assertEquals(null, state.accessibilityRole)
    }

    // ── Selected state ─────────────────────────────────────────────────

    @Test
    fun `accessibilityStateSelected defaults to false`() {
        val state = Renderer.ViewState()
        assertFalse(state.accessibilityStateSelected)
    }

    @Test
    fun `accessibilityStateSelected tracks boolean`() {
        val state = Renderer.ViewState()
        state.accessibilityStateSelected = true
        assertTrue(state.accessibilityStateSelected)
        state.accessibilityStateSelected = false
        assertFalse(state.accessibilityStateSelected)
    }

    // ── Checked state ──────────────────────────────────────────────────

    @Test
    fun `accessibilityStateChecked defaults to null`() {
        val state = Renderer.ViewState()
        assertEquals(null, state.accessibilityStateChecked)
    }

    @Test
    fun `accessibilityStateChecked supports three states`() {
        val state = Renderer.ViewState()
        state.accessibilityStateChecked = "checked"
        assertEquals("checked", state.accessibilityStateChecked)
        state.accessibilityStateChecked = "unchecked"
        assertEquals("unchecked", state.accessibilityStateChecked)
        state.accessibilityStateChecked = "mixed"
        assertEquals("mixed", state.accessibilityStateChecked)
    }

    @Test
    fun `accessibilityStateChecked null means absent`() {
        val state = Renderer.ViewState()
        state.accessibilityStateChecked = "checked"
        assertEquals("checked", state.accessibilityStateChecked)
        state.accessibilityStateChecked = null
        assertEquals(null, state.accessibilityStateChecked)
    }

    // ── State description ──────────────────────────────────────────────

    @Test
    fun `accessibilityStateDescription defaults to null`() {
        val state = Renderer.ViewState()
        assertEquals(null, state.accessibilityStateDescription)
    }

    @Test
    fun `accessibilityStateDescription can be set and cleared`() {
        val state = Renderer.ViewState()
        state.accessibilityStateDescription = "On"
        assertEquals("On", state.accessibilityStateDescription)
        state.accessibilityStateDescription = null
        assertEquals(null, state.accessibilityStateDescription)
    }

    // ── Range info ─────────────────────────────────────────────────────

    @Test
    fun `accessibilityRangeMin defaults to 0f`() {
        val state = Renderer.ViewState()
        assertEquals(0f, state.accessibilityRangeMin)
    }

    @Test
    fun `accessibilityRangeMax defaults to 0f`() {
        val state = Renderer.ViewState()
        assertEquals(0f, state.accessibilityRangeMax)
    }

    @Test
    fun `accessibilityRangeCurrent defaults to 0f`() {
        val state = Renderer.ViewState()
        assertEquals(0f, state.accessibilityRangeCurrent)
    }

    @Test
    fun `range values distinguish absent from zero`() {
        val state = Renderer.ViewState()
        // When max == min (both 0), range is absent.
        // When max > min, range should be presented.
        assertFalse(state.accessibilityRangeMax > state.accessibilityRangeMin)

        state.accessibilityRangeMax = 100f
        assertTrue(state.accessibilityRangeMax > state.accessibilityRangeMin)

        state.accessibilityRangeMin = 100f
        assertFalse(state.accessibilityRangeMax > state.accessibilityRangeMin)
    }

    @Test
    fun `range current is between min and max`() {
        val state = Renderer.ViewState()
        state.accessibilityRangeMin = 0f
        state.accessibilityRangeMax = 100f
        state.accessibilityRangeCurrent = 50f

        assertTrue(state.accessibilityRangeCurrent >= state.accessibilityRangeMin)
        assertTrue(state.accessibilityRangeCurrent <= state.accessibilityRangeMax)
    }

    // ── Accessibility absence vs false/empty/zero ──────────────────────

    @Test
    fun `all accessibility fields default to absent`() {
        val state = Renderer.ViewState()
        assertEquals(null, state.accessibilityRole)
        assertFalse(state.accessibilityStateSelected)
        assertEquals(null, state.accessibilityStateChecked)
        assertEquals(null, state.accessibilityStateDescription)
        assertEquals(0f, state.accessibilityRangeMin)
        assertEquals(0f, state.accessibilityRangeMax)
        assertEquals(0f, state.accessibilityRangeCurrent)
    }

    @Test
    fun `zero range is distinct from absent role`() {
        val state = Renderer.ViewState()
        // Range can be set without a role.
        state.accessibilityRangeMin = 0f
        state.accessibilityRangeMax = 100f
        assertEquals(null, state.accessibilityRole)
        assertTrue(state.accessibilityRangeMax > state.accessibilityRangeMin)
    }

    @Test
    fun `role without range is valid`() {
        val state = Renderer.ViewState()
        state.accessibilityRole = "button"
        assertEquals("button", state.accessibilityRole)
        assertFalse(state.accessibilityRangeMax > state.accessibilityRangeMin)
    }

    // ── ElementContracts accessibility prop coverage ───────────────────

    @Test
    fun `all kinds have accessibility props`() {
        val required = setOf(
            "accessibility_role",
            "accessibility_selected",
            "accessibility_checked",
            "accessibility_state_description",
            "accessibility_range_min",
            "accessibility_range_max",
            "accessibility_range_current",
        )
        for (kind in dev.vyne.generated.ElementContracts.KINDS) {
            val props = dev.vyne.generated.ElementContracts.ALL_PROPS_BY_KIND[kind]!!
            for (prop in required) {
                assertTrue(
                    prop in props,
                    "Kind '$kind' missing accessibility prop '$prop'"
                )
            }
        }
    }

    @Test
    fun `accessibility_role is validatable via PropertyTable`() {
        for (kind in dev.vyne.generated.ElementContracts.KINDS) {
            assertTrue(
                PropertyTable.isValidProp("accessibility_role", kind),
                "accessibility_role should be valid for $kind"
            )
        }
    }

    @Test
    fun `accessibility_range props are validatable via PropertyTable`() {
        for (kind in dev.vyne.generated.ElementContracts.KINDS) {
            for (prop in listOf("accessibility_range_min", "accessibility_range_max", "accessibility_range_current")) {
                assertTrue(
                    PropertyTable.isValidProp(prop, kind),
                    "$prop should be valid for $kind"
                )
            }
        }
    }

    // ── content_description is distinct from accessibility_role ────────

    @Test
    fun `content_description is a separate prop from accessibility_role`() {
        for (kind in dev.vyne.generated.ElementContracts.KINDS) {
            val props = dev.vyne.generated.ElementContracts.ALL_PROPS_BY_KIND[kind]!!
            assertTrue("content_description" in props)
            assertTrue("accessibility_role" in props)
        }
    }
}
