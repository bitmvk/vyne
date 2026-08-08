package dev.vyne

import kotlin.math.min

/** Mechanical max-size contract applied by registered container Views. */
internal interface MaxConstrainedView {
    var vyneMaxWidthPx: Int
    var vyneMaxHeightPx: Int
}

internal fun MaxConstrainedView.constrainMeasured(width: Int, height: Int): Pair<Int, Int> =
    (if (vyneMaxWidthPx > 0) min(width, vyneMaxWidthPx) else width) to
        (if (vyneMaxHeightPx > 0) min(height, vyneMaxHeightPx) else height)
