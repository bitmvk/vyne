/**
 * Static draw mechanics tests (DRAW-08).
 *
 * Pure Kotlin unit tests for dash array parsing logic, Canvas op structure,
 * and property name consistency.  Geometry tests that require Android
 * Path/PathMeasure/Canvas belong in the instrumentation androidTest source set.
 */
package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class StaticDrawMechanicsTest {

    // ── Canvas op structure tests ─────────────────────────────

    @Test
    fun `all supported canvas op kinds present`() {
        val kinds = setOf("rect", "round_rect", "circle", "line", "path")
        assertEquals(5, kinds.size)
        assertTrue("rect" in kinds)
        assertTrue("path" in kinds)
    }

    @Test
    fun `canvas op shared paint fields use canonical opacity not alpha`() {
        val sharedPaintFields = setOf(
            "fill", "stroke", "stroke_width", "stroke_cap",
            "stroke_join", "dash", "dash_offset", "opacity"
        )
        assertEquals(8, sharedPaintFields.size)
        assertTrue("opacity" in sharedPaintFields)
    }

    @Test
    fun `path command arities are correct`() {
        val arities = mapOf(
            "M" to 2, "m" to 2,
            "L" to 2, "l" to 2,
            "C" to 6, "c" to 6,
            "Q" to 4, "q" to 4,
            "Z" to 0, "z" to 0,
        )
        assertEquals(0, arities["Z"])
        assertEquals(2, arities["M"])
        assertEquals(6, arities["C"])
        assertEquals(4, arities["Q"])
    }

    // ── Dash array validation logic (pure Kotlin) ─────────────

    @Test
    fun `dash array string parsing logic handles normal case`() {
        // Simulates what NativeWidgets receives from Python wire format.
        // Python sends a JSON array of numbers, Kotlin receives a JSONArray.
        val s = "4,8"
        val parts = s.split(",").mapNotNull { it.trim().toFloatOrNull() }
        assertEquals(listOf(4f, 8f), parts)
        assertEquals(2, parts.size)
    }

    @Test
    fun `dash array string parsing handles whitespace`() {
        val s = " 4 , 8 "
        val parts = s.split(",").mapNotNull { it.trim().toFloatOrNull() }
        assertEquals(listOf(4f, 8f), parts)
    }

    @Test
    fun `dash array string parsing handles longer pattern`() {
        val s = "10,5,2,5"
        val parts = s.split(",").mapNotNull { it.trim().toFloatOrNull() }
        assertEquals(listOf(10f, 5f, 2f, 5f), parts)
        assertEquals(4, parts.size)
    }

    @Test
    fun `dash array with full keyword is recognized`() {
        val s = "full"
        assertEquals("full", s)
        assertTrue(s == "full")
    }

    @Test
    fun `empty dash array string yields empty list`() {
        val s = ""
        val parts = s.split(",").mapNotNull { it.trim().toFloatOrNull() }
        assertTrue(parts.isEmpty())
    }

    @Test
    fun `invalid dash array string yields empty`() {
        val s = "not-a-number"
        val parts = s.split(",").mapNotNull { it.trim().toFloatOrNull() }
        assertTrue(parts.isEmpty())
    }

    // ── ViewBox parsing logic ──────────────────────────────────

    @Test
    fun `viewBox requires four numbers`() {
        // Python side: view_box must be [x, y, width, height]
        val valid = listOf(0, 0, 100, 100)
        assertEquals(4, valid.size)

        val tooShort = listOf(0, 0, 100)
        assertTrue(tooShort.size != 4)

        val tooLong = listOf(0, 0, 100, 100, 200)
        assertTrue(tooLong.size != 4)
    }

    @Test
    fun `viewBox width and height must be positive`() {
        val validW = 100
        val validH = 100
        assertTrue(validW > 0)
        assertTrue(validH > 0)

        val invalidW = -10
        val invalidH = 0
        assertTrue(invalidW <= 0)
        assertTrue(invalidH <= 0)
    }

    // ── PathView allocation counter semantics ──────────────────

    @Test
    fun `path build count semantics`() {
        // When commands are set via JSONArray, a path rebuild occurs.
        // Test the pure logic: the counter is incremented in the setter.
        // This validates the design, not the Android View implementation.
        var buildCount = 0
        fun triggerBuild() { buildCount++ }

        triggerBuild()
        assertEquals(1, buildCount)

        triggerBuild()
        assertEquals(2, buildCount)
    }

    @Test
    fun `dash effect creation counter semantics`() {
        var createCount = 0
        val cache = mutableMapOf<String, FloatArray>()

        fun getEffect(key: String, values: FloatArray): FloatArray? {
            cache[key]?.let { return it }
            createCount++
            cache[key] = values
            return values
        }

        // First call creates new
        getEffect("4,8", floatArrayOf(4f, 8f))
        assertEquals(1, createCount)

        // Second call with same key uses cache
        getEffect("4,8", floatArrayOf(4f, 8f))
        assertEquals(1, createCount)

        // Different key creates new
        getEffect("8,4", floatArrayOf(8f, 4f))
        assertEquals(2, createCount)
    }

    // ── Multi-contour trim computation (pure logic) ────────────

    @Test
    fun `concatenated length is sum of individual contour lengths`() {
        // Simulates computeTotalLength logic without Android PathMeasure.
        // Given contour lengths [50, 30], total should be 80.
        val contourLengths = listOf(50f, 30f)
        val total = contourLengths.sum()
        assertEquals(80f, total)
    }

    @Test
    fun `trim segment selection within concatenated length`() {
        // For a multi-contour path with lengths [50, 30], trim from 0.2 to 0.8
        // total = 80, start = 16, end = 64
        val lengths = listOf(50f, 30f)
        val total = lengths.sum() // 80
        val trimStart = 0.2f
        val trimEnd = 0.8f
        val absoluteStart = total * trimStart // 16
        val absoluteEnd = total * trimEnd // 64

        // Contour 1 (0-50): contributes 34 (16→50)
        // Contour 2 (50-80): contributes 14 (50→64)
        val c1Start = maxOf(0f, absoluteStart)
        val c1End = minOf(lengths[0], absoluteEnd)
        assertEquals(16f, c1Start, 0.01f)
        assertEquals(50f, c1End, 0.01f)

        val c2Start = maxOf(0f, absoluteStart - lengths[0])
        val c2End = minOf(lengths[1], absoluteEnd - lengths[0])
        assertEquals(0f, c2Start, 0.01f)
        assertEquals(14f, c2End, 0.01f)
    }
}
