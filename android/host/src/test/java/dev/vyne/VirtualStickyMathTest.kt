package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Pure positioning-math tests for native sticky headers/footers.
 *
 * Exercises half-open activation, start/end clamping, section push-off,
 * before/after-section restoration, and degenerate inputs — all in content
 * coordinates, so vertical and horizontal hosts share exactly one
 * implementation (verified through the driver in VirtualStickyDriverTest).
 */
class VirtualStickyMathTest {

    private fun position(
        natural: Float,
        extent: Float,
        viewportStart: Float,
        viewportEnd: Float,
        boundaryStart: Float,
        boundaryEnd: Float,
        edge: String?,
    ) = computeStickyPosition(
        natural, extent, viewportStart, viewportEnd,
        boundaryStart, boundaryEnd, edge,
    )

    // ── Half-open activation ──────────────────────────────────────────

    @Test
    fun inactiveWhenViewportBelowBoundary() {
        // Boundary [0,230), viewport fully above it.
        val result = position(0f, 30f, -40f, 0f, 0f, 230f, "start")
        assertEquals(0f, result.main)
        assertFalse(result.displaced)
    }

    @Test
    fun inactiveWhenViewportStartsExactlyAtBoundaryEnd() {
        // Half-open: viewportStart == boundaryEnd is outside.
        val result = position(0f, 30f, 230f, 330f, 0f, 230f, "start")
        assertEquals(0f, result.main)
        assertFalse(result.displaced)
    }

    @Test
    fun inactiveWhenViewportEndsExactlyAtBoundaryStart() {
        val result = position(190f, 40f, 100f, 230f, 0f, 230f, "end")
        assertEquals(190f, result.main)
        assertFalse(result.displaced)
    }

    @Test
    fun activeWhenOverlapping() {
        val result = position(0f, 30f, 50f, 150f, 0f, 230f, "start")
        assertTrue(result.displaced)
        assertEquals(50f, result.main)
    }

    // ── Start / header clamping ───────────────────────────────────────

    @Test
    fun headerSticksToViewportTopWithinSection() {
        val result = position(0f, 30f, 120f, 220f, 0f, 230f, "start")
        assertEquals(120f, result.main)
        assertTrue(result.displaced)
    }

    @Test
    fun headerNeverLeavesItsSectionBottom() {
        // viewportStart approaches the boundary end; the header is pushed off
        // but pinned at boundaryEnd - extent while still overlapping.
        val result = position(0f, 30f, 220f, 320f, 0f, 230f, "start")
        assertEquals(200f, result.main)
        assertTrue(result.displaced)
    }

    @Test
    fun headerNaturalWhenSectionNotYetReached() {
        // Section below the viewport: boundary [500, 730), viewport [0, 100].
        val result = position(500f, 30f, 0f, 100f, 500f, 730f, "start")
        assertEquals(500f, result.main)
        assertFalse(result.displaced)
    }

    @Test
    fun headerPinnedAtSectionTopWhenViewportTopInsideSection() {
        val result = position(460f, 30f, 480f, 540f, 460f, 690f, "start")
        assertEquals(480f, result.main)
        assertTrue(result.displaced)
    }

    // ── End / footer clamping ─────────────────────────────────────────

    @Test
    fun footerSticksToViewportBottomWithinSection() {
        // Footer natural 190 (section bottom), viewport [0,100], extent 40.
        val result = position(190f, 40f, 0f, 100f, 0f, 230f, "end")
        assertEquals(60f, result.main)
        assertTrue(result.displaced)
    }

    @Test
    fun footerPinnedToSectionTopWhileViewportBottomStillInHeaderRegion() {
        val result = position(190f, 40f, 0f, 30f, 0f, 230f, "end")
        assertEquals(0f, result.main)
        assertTrue(result.displaced)
    }

    @Test
    fun footerNaturalWhenFullyVisibleAboveViewportBottom() {
        val result = position(190f, 40f, 200f, 300f, 0f, 230f, "end")
        assertEquals(190f, result.main)
        assertFalse(result.displaced)
    }

    @Test
    fun footerRestoredAfterSectionPassed() {
        val result = position(190f, 40f, 230f, 330f, 0f, 230f, "end")
        assertEquals(190f, result.main)
        assertFalse(result.displaced)
    }

    // ── Both header and footer active simultaneously ─────────────────

    @Test
    fun headerAndFooterDisplacedTogether() {
        val header = position(230f, 30f, 300f, 380f, 230f, 460f, "start")
        val footer = position(420f, 40f, 300f, 380f, 230f, 460f, "end")
        assertEquals(300f, header.main)
        assertTrue(header.displaced)
        assertEquals(340f, footer.main)
        assertTrue(footer.displaced)
    }

    // ── Degenerate inputs ─────────────────────────────────────────────

    @Test
    fun degenerateCellLargerThanSectionKeepsNatural() {
        val result = position(0f, 60f, 50f, 150f, 0f, 40f, "start")
        assertEquals(0f, result.main)
        assertFalse(result.displaced)
    }

    @Test
    fun degenerateInvertedBoundaryKeepsNatural() {
        val result = position(0f, 30f, 50f, 150f, 60f, 20f, "start")
        assertEquals(0f, result.main)
        assertFalse(result.displaced)
    }

    @Test
    fun degenerateZeroSectionKeepsNatural() {
        val result = position(0f, 30f, 50f, 150f, 60f, 60f, "start")
        assertEquals(0f, result.main)
        assertFalse(result.displaced)
    }

    @Test
    fun unmeasuredZeroExtentIsHandled() {
        // A not-yet-measured cell (extent 0) computes without crashing and
        // sticks to the viewport top within its section.
        val result = position(0f, 0f, 10f, 110f, 0f, 230f, "start")
        assertEquals(10f, result.main)
    }

    @Test
    fun nullEdgeAlwaysNatural() {
        val result = position(7f, 30f, 50f, 150f, 0f, 230f, null)
        assertEquals(7f, result.main)
        assertFalse(result.displaced)
    }

    @Test
    fun unknownEdgeIsTreatedAsNatural() {
        // Defensive fallback: an unrecognized edge must never displace the
        // cell (the schema already rejects such values on the wire).
        val result = position(7f, 30f, 50f, 150f, 0f, 230f, "middle")
        assertEquals(7f, result.main)
        assertFalse(result.displaced)
    }

    // ── Axis equivalence ──────────────────────────────────────────────

    @Test
    fun sameFormulaForBothAxes() {
        // Vertical header at y=460 sticking to viewport top 500.
        val vertical = position(460f, 30f, 500f, 560f, 460f, 690f, "start")
        // Horizontal header at x=460 sticking to viewport start 500: the
        // exact same numbers; only natural/extent selection differs (driver).
        val horizontal = position(460f, 30f, 500f, 560f, 460f, 690f, "start")
        assertEquals(vertical, horizontal)
        assertEquals(500f, horizontal.main)
        assertTrue(horizontal.displaced)
    }
}
