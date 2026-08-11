package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Driver tests for the native sticky traversal.
 *
 * `updateStickyContent` is the exact function the Android scroll hosts call
 * per frame; driving it through fakes proves the marker gate (ordinary
 * content pays zero), the O(realized) index loop, restoration of non-sticky
 * cells, and simultaneous header+footer displacement — with no bridge events
 * or Python commits involved (the driver has no emission path at all).
 */
class VirtualStickyDriverTest {

    private class FakeCell(
        override var stickyEdge: String? = null,
        override var stickyBoundaryStartPx: Float = 0f,
        override var stickyBoundaryEndPx: Float = 0f,
        override var naturalTranslationX: Float = 0f,
        override var naturalTranslationY: Float = 0f,
        override var widthPx: Float = 40f,
        override var heightPx: Float = 40f,
    ) : VirtualStickyCell {
        var appliedMain: Float = Float.NaN
        var appliedDisplaced: Boolean = false
        var applyCount: Int = 0
        var lastVertical: Boolean? = null

        // Simulated visible translations of the wrapper, mirroring the view
        // fields the real RoundedFrameLayout keeps for the two axes.
        var visibleX: Float = naturalTranslationX
        var visibleY: Float = naturalTranslationY

        override fun applyStickyPosition(
            vertical: Boolean,
            main: Float,
            displaced: Boolean,
        ) {
            appliedMain = main
            appliedDisplaced = displaced
            applyCount++
            lastVertical = vertical
            if (vertical) visibleY = main else visibleX = main
        }

        override fun restoreNaturalPosition() {
            visibleX = naturalTranslationX
            visibleY = naturalTranslationY
        }
    }

    private class FakeContent(
        override var isVirtualContent: Boolean = true,
        private val cells: List<FakeCell>,
    ) : VirtualStickyContent {
        override var stickyViewportStart: Float = 0f
        override var stickyViewportEnd: Float = 0f
        override var stickyVertical: Boolean = false
        override val cellCount: Int get() = cells.size
        override fun cellAt(index: Int): VirtualStickyCell? =
            cells.getOrNull(index)
    }

    @Test
    fun unmarkedContentIsNotTraversed() {
        val cell = FakeCell(stickyEdge = "start", naturalTranslationY = 0f, heightPx = 30f)
        val content = FakeContent(isVirtualContent = false, cells = listOf(cell))
        val visited = updateStickyContent(content, 50f, 150f, vertical = true)
        assertEquals(0, visited)
        assertEquals(0, cell.applyCount)
    }

    @Test
    fun nonStickyCellsAreVisitedAndRestoredToNatural() {
        val plain = FakeCell(naturalTranslationY = 120f, heightPx = 40f)
        val content = FakeContent(isVirtualContent = true, cells = listOf(plain))
        val visited = updateStickyContent(content, 50f, 150f, vertical = true)
        assertEquals(1, visited)
        assertEquals(120f, plain.appliedMain)
        assertFalse(plain.appliedDisplaced)
    }

    @Test
    fun visitedCountIsProportionalToRealizedChildren() {
        val cells = (0 until 64).map {
            FakeCell(naturalTranslationY = it * 40f, heightPx = 40f)
        }
        val content = FakeContent(isVirtualContent = true, cells = cells)
        val visited = updateStickyContent(content, 0f, 400f, vertical = true)
        assertEquals(64, visited)
        cells.forEachIndexed { index, cell ->
            assertEquals(index * 40f, cell.appliedMain)
        }
    }

    @Test
    fun verticalHeaderAndFooterDisplacedTogether() {
        // Section [230, 460); viewport [300, 380).
        val header = FakeCell(
            stickyEdge = "start",
            stickyBoundaryStartPx = 230f,
            stickyBoundaryEndPx = 460f,
            naturalTranslationY = 230f,
            heightPx = 30f,
        )
        val footer = FakeCell(
            stickyEdge = "end",
            stickyBoundaryStartPx = 230f,
            stickyBoundaryEndPx = 460f,
            naturalTranslationY = 420f,
            heightPx = 40f,
        )
        val content = FakeContent(
            isVirtualContent = true,
            cells = listOf(header, footer),
        )
        updateStickyContent(content, 300f, 380f, vertical = true)
        assertEquals(300f, header.appliedMain)
        assertTrue(header.appliedDisplaced)
        assertEquals(340f, footer.appliedMain)
        assertTrue(footer.appliedDisplaced)
    }

    @Test
    fun horizontalAxisUsesWidthAndTranslationX() {
        // Horizontal section [230, 460); viewport [300, 380).
        val header = FakeCell(
            stickyEdge = "start",
            stickyBoundaryStartPx = 230f,
            stickyBoundaryEndPx = 460f,
            naturalTranslationX = 230f,
            widthPx = 30f,
        )
        val content = FakeContent(isVirtualContent = true, cells = listOf(header))
        updateStickyContent(content, 300f, 380f, vertical = false)
        assertEquals(300f, header.appliedMain)
        assertTrue(header.appliedDisplaced)
    }

    @Test
    fun naturalPositionRestoredWhenViewportLeavesBoundary() {
        val header = FakeCell(
            stickyEdge = "start",
            stickyBoundaryStartPx = 0f,
            stickyBoundaryEndPx = 230f,
            naturalTranslationY = 0f,
            heightPx = 30f,
        )
        val content = FakeContent(isVirtualContent = true, cells = listOf(header))
        updateStickyContent(content, 50f, 150f, vertical = true)
        assertEquals(50f, header.appliedMain)
        assertTrue(header.appliedDisplaced)
        // Scroll past the section end: restored to natural.
        updateStickyContent(content, 230f, 330f, vertical = true)
        assertEquals(0f, header.appliedMain)
        assertFalse(header.appliedDisplaced)
    }

    @Test
    fun headerPushedOffAtSectionEnd() {
        val header = FakeCell(
            stickyEdge = "start",
            stickyBoundaryStartPx = 460f,
            stickyBoundaryEndPx = 690f,
            naturalTranslationY = 460f,
            heightPx = 30f,
        )
        val content = FakeContent(isVirtualContent = true, cells = listOf(header))
        // Viewport start past the movable range but still overlapping the
        // boundary: the header is pinned at the section's bottom edge while
        // the next section pushes it off.
        updateStickyContent(content, 665f, 725f, vertical = true)
        assertEquals(660f, header.appliedMain)
        assertTrue(header.appliedDisplaced)
        // One more viewport: fully past the section, back to natural.
        updateStickyContent(content, 690f, 750f, vertical = true)
        assertEquals(460f, header.appliedMain)
        assertFalse(header.appliedDisplaced)
    }

    // ── Lifecycle mechanics (boundary-only updates, per-axis reset, ──
    // ── marker removal) through the production driver/helpers ─────────

    @Test
    fun boundaryOnlyUpdateReDisplacesOnStationaryViewport() {
        // Section [230, 460); viewport [300, 380) never moves and the cell's
        // placed (natural) position never changes: only the layout-defined
        // boundary interval is updated, exactly what a measurement-driven
        // prop change publishes while the list is static.
        val cell = FakeCell(
            stickyEdge = "start",
            stickyBoundaryStartPx = 230f,
            stickyBoundaryEndPx = 460f,
            naturalTranslationY = 230f,
            heightPx = 30f,
        )
        val content = FakeContent(isVirtualContent = true, cells = listOf(cell))
        updateStickyContent(content, 300f, 380f, vertical = true)
        assertEquals(300f, cell.appliedMain)
        assertTrue(cell.appliedDisplaced)
        // Boundary-only update: the new interval no longer overlaps the
        // stationary viewport, so the cell returns to natural without any
        // scroll or layout.
        cell.stickyBoundaryStartPx = 0f
        cell.stickyBoundaryEndPx = 240f
        updateStickyContent(content, 300f, 380f, vertical = true)
        assertEquals(230f, cell.appliedMain)
        assertFalse(cell.appliedDisplaced)
        // A second boundary-only update re-activates from natural.
        cell.stickyBoundaryStartPx = 230f
        cell.stickyBoundaryEndPx = 460f
        updateStickyContent(content, 300f, 380f, vertical = true)
        assertEquals(300f, cell.appliedMain)
        assertTrue(cell.appliedDisplaced)
    }

    @Test
    fun oneAxisResetPreservesTheOtherAxisDisplacement() {
        // Horizontal sticky cell: the main axis is X.
        val cell = FakeCell(
            stickyEdge = "start",
            stickyBoundaryStartPx = 230f,
            stickyBoundaryEndPx = 460f,
            naturalTranslationX = 230f,
            widthPx = 30f,
        )
        val content = FakeContent(isVirtualContent = true, cells = listOf(cell))
        updateStickyContent(content, 300f, 380f, vertical = false)
        assertEquals(300f, cell.visibleX)
        assertTrue(cell.appliedDisplaced)
        // translation_x removal: reset the X natural/visible axis only (the
        // production resetNaturalX), then re-apply any active displacement.
        cell.naturalTranslationX = 0f
        cell.visibleX = 0f
        updateStickyContent(content, 300f, 380f, vertical = false)
        assertEquals(300f, cell.visibleX)
        assertTrue(cell.appliedDisplaced)
        // The Y axis and its natural position were never touched, and every
        // apply stayed on the horizontal axis.
        assertEquals(0f, cell.visibleY)
        assertEquals(false, cell.lastVertical)
    }

    @Test
    fun unmarkingContentRestoresEveryCellToNatural() {
        val header = FakeCell(
            stickyEdge = "start",
            stickyBoundaryStartPx = 230f,
            stickyBoundaryEndPx = 460f,
            naturalTranslationY = 230f,
            heightPx = 30f,
        )
        val footer = FakeCell(
            stickyEdge = "end",
            stickyBoundaryStartPx = 230f,
            stickyBoundaryEndPx = 460f,
            naturalTranslationY = 420f,
            heightPx = 40f,
        )
        val content = FakeContent(
            isVirtualContent = true,
            cells = listOf(header, footer),
        )
        updateStickyContent(content, 300f, 380f, vertical = true)
        assertTrue(header.appliedDisplaced)
        assertTrue(footer.appliedDisplaced)
        // Marker removal: the production handler clears the marker and runs
        // restoreVirtualContent over the direct children.
        content.isVirtualContent = false
        restoreVirtualContent(content)
        assertEquals(230f, header.visibleY)
        assertEquals(420f, footer.visibleY)
    }

    @Test
    fun unknownEdgeIsNaturalThroughDriver() {
        // The schema rejects unknown edges on the wire, but the native pass
        // must still fall back to natural flow defensively.
        val cell = FakeCell(
            stickyEdge = "middle",
            stickyBoundaryStartPx = 230f,
            stickyBoundaryEndPx = 460f,
            naturalTranslationY = 230f,
            heightPx = 30f,
        )
        val content = FakeContent(isVirtualContent = true, cells = listOf(cell))
        updateStickyContent(content, 300f, 380f, vertical = true)
        assertEquals(230f, cell.appliedMain)
        assertFalse(cell.appliedDisplaced)
    }
}
