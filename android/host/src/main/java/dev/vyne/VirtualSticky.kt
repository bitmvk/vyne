package dev.vyne

/**
 * Native sticky-header/footer mechanics for the generic virtual list.
 *
 * Python owns realization and publishes, for each sticky cell, its natural
 * placed position (``translation_x``/``y``) plus a private boundary interval
 * (the layout-defined section) and the viewport edge it sticks to.  The
 * native scroll host applies the displacement on every scroll frame — no
 * bridge event, no Python commit, no layout — by translating the cell
 * wrapper inside the marked content Box.
 *
 * The positioning math is deliberately a pure function of primitives so the
 * JVM test suite can exhaustively exercise activation, start/end clamping,
 * section push-off, and degenerate inputs without an Android runtime.
 * `updateStickyContent` is the traversal driver shared by the scroll hosts
 * and the JVM tests: it is gated on the content marker, loops only over the
 * realized direct children, and emits no events or per-frame allocations.
 */

/** A positioned virtual cell that the native host may displace. */
internal interface VirtualStickyCell {
    val stickyEdge: String?
    val stickyBoundaryStartPx: Float
    val stickyBoundaryEndPx: Float
    val naturalTranslationX: Float
    val naturalTranslationY: Float
    val widthPx: Float
    val heightPx: Float

    /** Apply one main-axis position; `displaced` raises the paint order. */
    fun applyStickyPosition(vertical: Boolean, main: Float, displaced: Boolean)

    /**
     * Restore the natural placed position on both axes and clear the paint Z.
     *
     * Used when a cell loses its sticky metadata or its content Box stops
     * being virtual content, so the wrapper never stays displaced.
     */
    fun restoreNaturalPosition()
}

/** The content Box of a virtual list: marker + realized direct children. */
internal interface VirtualStickyContent {
    val isVirtualContent: Boolean
    val cellCount: Int
    fun cellAt(index: Int): VirtualStickyCell?

    /** Last viewport the host published, used to re-displace after prop updates. */
    var stickyViewportStart: Float
    var stickyViewportEnd: Float
    var stickyVertical: Boolean
}

/** Result of one sticky computation, in content coordinates. */
internal data class StickyPosition(val main: Float, val displaced: Boolean)

/**
 * Compute the main-axis position of one sticky cell (content coordinates).
 *
 * Half-open activation: the cell is displaced only while the viewport
 * overlaps its boundary interval ``[boundaryStart, boundaryEnd)``; outside
 * that overlap the cell returns to its natural position.  Start/header cells
 * clamp ``max(natural, viewportStart)`` into the movable range, so the header
 * pins to the viewport top and is pushed off at its section end.  End/footer
 * cells clamp ``min(natural, viewportEnd - extent)``, so the footer pins to
 * the viewport bottom and is pushed off when the next section arrives.
 * A cell that cannot fit its section, or unmeasured bounds, keeps its
 * natural position.
 *
 * This allocation-free variant is the per-frame hot path; the driver and
 * ``refreshSticky`` call it directly.
 */
internal fun computeStickyMain(
    natural: Float,
    extent: Float,
    viewportStart: Float,
    viewportEnd: Float,
    boundaryStart: Float,
    boundaryEnd: Float,
    edge: String?,
): Float {
    // Any edge other than "start"/"end" (including null) is defensive
    // natural flow: the schema already rejects unknown edges on the wire,
    // but the native math must never displace a cell it does not recognize.
    if (edge != "start" && edge != "end") return natural
    if (boundaryStart >= viewportEnd || viewportStart >= boundaryEnd) {
        // Viewport does not overlap the boundary interval (half-open).
        return natural
    }
    val section = boundaryEnd - boundaryStart
    if (section <= 0f || extent >= section) {
        // Degenerate bounds or a cell larger than its section: natural flow.
        return natural
    }
    val upper = boundaryEnd - extent
    return if (edge == "start") {
        maxOf(natural, viewportStart).coerceIn(boundaryStart, upper)
    } else {
        minOf(natural, viewportEnd - extent).coerceIn(boundaryStart, upper)
    }
}

/** Convenience wrapper used by tests; the hot path uses `computeStickyMain`. */
internal fun computeStickyPosition(
    natural: Float,
    extent: Float,
    viewportStart: Float,
    viewportEnd: Float,
    boundaryStart: Float,
    boundaryEnd: Float,
    edge: String?,
): StickyPosition {
    val main = computeStickyMain(
        natural, extent, viewportStart, viewportEnd, boundaryStart, boundaryEnd, edge,
    )
    return StickyPosition(main, main != natural)
}

/**
 * Refresh every realized sticky cell of one marked content Box.
 *
 * Returns the number of direct children visited so callers and tests can
 * assert the pass is proportional to the realized window (and zero for
 * ordinary, unmarked content).  Non-sticky children are visited but simply
 * restored to their natural translation.
 */
internal fun updateStickyContent(
    content: VirtualStickyContent,
    viewportStart: Float,
    viewportEnd: Float,
    vertical: Boolean,
): Int {
    if (!content.isVirtualContent) return 0
    var visited = 0
    val count = content.cellCount
    var i = 0
    while (i < count) {
        val cell = content.cellAt(i)
        if (cell != null) {
            visited++
            val natural =
                if (vertical) cell.naturalTranslationY else cell.naturalTranslationX
            val extent = if (vertical) cell.heightPx else cell.widthPx
            val target = computeStickyMain(
                natural,
                extent,
                viewportStart,
                viewportEnd,
                cell.stickyBoundaryStartPx,
                cell.stickyBoundaryEndPx,
                cell.stickyEdge,
            )
            cell.applyStickyPosition(vertical, target, target != natural)
        }
        i++
    }
    return visited
}

/**
 * Restore every realized direct child of a virtual content Box to its
 * natural placed position.
 *
 * Runs when the content Box loses its virtual marker (remove or explicit
 * false), so no cell is left displaced once the native sticky pass stops.
 */
internal fun restoreVirtualContent(content: VirtualStickyContent) {
    val count = content.cellCount
    var i = 0
    while (i < count) {
        content.cellAt(i)?.restoreNaturalPosition()
        i++
    }
}

/** Paint elevation applied only while a sticky cell is displaced. */
internal const val STICKY_Z_PX: Float = 1f
