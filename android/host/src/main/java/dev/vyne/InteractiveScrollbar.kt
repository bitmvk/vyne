package dev.vyne

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.MotionEvent
import kotlin.math.roundToInt

internal const val INTERACTIVE_SCROLLBAR_MIN_THUMB_DP = 40f
internal const val INTERACTIVE_SCROLLBAR_TOUCH_TARGET_DP = 32f
internal const val INTERACTIVE_SCROLLBAR_VISUAL_THICKNESS_DP = 7f
internal const val VIRTUAL_SCROLL_SEEK_EMIT_INTERVAL_MS = 32L
internal const val VIRTUAL_SCROLL_SEEK_WATCHDOG_MS = 750L
internal const val VIRTUAL_SCROLL_SEEK_MAX_RETRIES = 2
internal const val VIRTUAL_SCROLL_SEEK_TARGET_TOLERANCE_PX = 1

/** Nearest-pixel conversion for a logical scroll offset crossing the bridge. */
internal fun logicalScrollOffsetToPx(offset: Float, density: Float): Int =
    (offset * density).roundToInt().coerceAtLeast(0)

internal data class VirtualScrollSeekEmission(
    val target: Int,
    val final: Boolean,
)

/**
 * Pure latest-target state for transactional virtual-list seeking.
 *
 * There is deliberately no native in-flight latch. Runtime's existing latest
 * event delivery and one-in-flight transaction rule provide backpressure.
 */
internal class VirtualScrollSeekState {
    private var lastNonFinalEmitTime = Long.MIN_VALUE
    private var finalTarget: Int? = null
    private var retries = 0

    var provisionalTarget: Int? = null
        private set

    val finalPending: Boolean get() = finalTarget != null

    fun beginGesture() {
        reset()
    }

    fun updateTarget(
        target: Int,
        eventTime: Long,
        final: Boolean,
    ): VirtualScrollSeekEmission? {
        val bounded = target.coerceAtLeast(0)
        provisionalTarget = bounded
        if (final) {
            finalTarget = bounded
            retries = 0
            return recordEmission(bounded, final = true)
        }
        val due = lastNonFinalEmitTime == Long.MIN_VALUE ||
            eventTime - lastNonFinalEmitTime >= VIRTUAL_SCROLL_SEEK_EMIT_INTERVAL_MS
        if (!due) return null
        lastNonFinalEmitTime = eventTime
        return recordEmission(bounded, final = false)
    }

    /**
     * Accept one prepared non-animated reveal while a seek is provisional.
     *
     * No target history is needed: any such ScrollTo was prepared by Python
     * before native reveal, so suppressing its echo is safe. An older reveal
     * leaves the newer provisional target intact. The one-pixel tolerance is
     * only for Float dp↔px round trips at host density.
     */
    fun acceptReveal(target: Int): Boolean {
        if (provisionalTarget == null && finalTarget == null) return false
        if (targetsMatch(provisionalTarget, target)) provisionalTarget = null
        if (targetsMatch(finalTarget, target)) {
            finalTarget = null
            retries = 0
        }
        return true
    }

    /** Retry the final target twice, then abandon the provisional thumb. */
    fun watchdog(actualTarget: Int): VirtualScrollSeekEmission? {
        val target = finalTarget ?: return null
        if (targetsMatch(actualTarget, target)) {
            provisionalTarget = null
            finalTarget = null
            retries = 0
            return null
        }
        if (retries < VIRTUAL_SCROLL_SEEK_MAX_RETRIES) {
            retries += 1
            return recordEmission(target, final = true)
        }
        reset()
        return null
    }

    fun displayTarget(actualTarget: Int): Int = provisionalTarget ?: actualTarget

    fun reset() {
        provisionalTarget = null
        finalTarget = null
        retries = 0
        lastNonFinalEmitTime = Long.MIN_VALUE
    }

    private fun recordEmission(target: Int, final: Boolean): VirtualScrollSeekEmission =
        VirtualScrollSeekEmission(target, final)

    private fun targetsMatch(first: Int?, second: Int): Boolean =
        first != null && kotlin.math.abs(first.toLong() - second.toLong()) <=
            VIRTUAL_SCROLL_SEEK_TARGET_TOLERANCE_PX
}

internal typealias VirtualScrollSeekListener =
    (targetX: Int, targetY: Int, final: Boolean, eventTime: Long) -> Unit

/** Axis adapter plus target-specific metrics-echo suppression. */
internal class VirtualScrollSeekHostState(private val vertical: Boolean) {
    private val state = VirtualScrollSeekState()
    private var suppressX = 0
    private var suppressY = 0
    private var suppressUntil = 0L

    var listener: VirtualScrollSeekListener? = null
        private set

    val enabled: Boolean get() = listener != null
    val finalPending: Boolean get() = state.finalPending

    fun setListener(value: VirtualScrollSeekListener?) {
        // Listener replacement/removal may be a candidate transaction which
        // still can roll back. Preserve seek state until accepted cleanup.
        listener = value
    }

    fun beginGesture() {
        state.beginGesture()
        clearSuppression()
    }

    fun update(target: Int, eventTime: Long, final: Boolean) {
        val emission = state.updateTarget(target, eventTime, final) ?: return
        emit(emission, eventTime)
    }

    fun retry(actual: Int, eventTime: Long) {
        val emission = state.watchdog(actual) ?: return
        emit(emission, eventTime)
    }

    fun displayOffset(actual: Int): Int = state.displayTarget(actual)

    /** Mark one accepted, non-animated seek reveal before native scrollTo. */
    fun acceptReveal(x: Int, y: Int, now: Long): Boolean {
        val target = if (vertical) y else x
        if (!state.acceptReveal(target)) return false
        suppressX = x
        suppressY = y
        suppressUntil = now + 250L
        return true
    }

    fun consumeMetricsSuppression(x: Int, y: Int, now: Long): Boolean {
        if (suppressUntil == 0L) return false
        if (now > suppressUntil) {
            clearSuppression()
            return false
        }
        if (x != suppressX || y != suppressY) {
            // Real movement away from the reveal target must never be hidden.
            clearSuppression()
            return false
        }
        // Keep suppression through the short deadline so both synchronous
        // scroll and following layout observations of the same reveal drop.
        return true
    }

    fun reset() {
        state.reset()
        clearSuppression()
    }

    private fun emit(emission: VirtualScrollSeekEmission, eventTime: Long) {
        val callback = listener ?: return
        if (vertical) callback(0, emission.target, emission.final, eventTime)
        else callback(emission.target, 0, emission.final, eventTime)
    }

    private fun clearSuppression() {
        suppressX = 0
        suppressY = 0
        suppressUntil = 0L
    }
}

/** Axis-neutral geometry for the generic host-native scroll tool. */
internal data class InteractiveScrollbarGeometry(
    val trackStart: Float,
    val trackExtent: Float,
    val thumbStart: Float,
    val thumbExtent: Float,
    val maxScroll: Float,
) {
    val thumbEnd: Float get() = thumbStart + thumbExtent
    val thumbTravel: Float get() = trackExtent - thumbExtent
}

/** Mechanical math specified by the shared platform-host fixture. */
internal object InteractiveScrollbarMath {
    fun clampProjectedOffset(
        projectedOffset: Float,
        viewportExtent: Float,
        contentExtent: Float,
    ): Float = projectedOffset.coerceAtLeast(0f).coerceAtMost(
        (contentExtent - viewportExtent).coerceAtLeast(0f),
    )

    fun geometry(
        trackStart: Float,
        trackExtent: Float,
        viewportExtent: Float,
        contentExtent: Float,
        scrollOffset: Float,
        minimumThumbExtent: Float,
    ): InteractiveScrollbarGeometry? {
        if (
            trackExtent <= 0f || viewportExtent <= 0f ||
            contentExtent <= viewportExtent
        ) return null
        val maxScroll = contentExtent - viewportExtent
        val minimum = minimumThumbExtent.coerceIn(0f, trackExtent)
        val thumbExtent =
            (trackExtent * viewportExtent / contentExtent).coerceIn(minimum, trackExtent)
        val travel = trackExtent - thumbExtent
        val fraction = (scrollOffset / maxScroll).coerceIn(0f, 1f)
        return InteractiveScrollbarGeometry(
            trackStart = trackStart,
            trackExtent = trackExtent,
            thumbStart = trackStart + travel * fraction,
            thumbExtent = thumbExtent,
            maxScroll = maxScroll,
        )
    }

    fun grabOffset(pointer: Float, geometry: InteractiveScrollbarGeometry): Float =
        grabOffset(pointer, geometry.thumbStart, geometry.thumbExtent)

    fun grabOffset(pointer: Float, thumbStart: Float, thumbExtent: Float): Float =
        if (pointer in thumbStart..(thumbStart + thumbExtent)) {
            pointer - thumbStart
        } else {
            thumbExtent / 2f
        }

    fun targetOffset(
        pointer: Float,
        grabOffset: Float,
        geometry: InteractiveScrollbarGeometry,
    ): Int = targetOffset(
        pointer,
        grabOffset,
        geometry.trackStart,
        geometry.trackExtent,
        geometry.thumbExtent,
        geometry.maxScroll,
    )

    fun targetOffset(
        pointer: Float,
        grabOffset: Float,
        trackStart: Float,
        trackExtent: Float,
        thumbExtent: Float,
        maxScroll: Float,
    ): Int {
        val travel = trackExtent - thumbExtent
        if (travel <= 0f || maxScroll <= 0f) return 0
        val thumbStart = (pointer - grabOffset).coerceIn(
            trackStart,
            trackStart + travel,
        )
        val fraction = (thumbStart - trackStart) / travel
        return (fraction * maxScroll).roundToInt()
    }
}

/**
 * Generic frame-sensitive scrollbar tool for a native scroll container.
 *
 * It has no item, key, layout, or virtualization knowledge. Python selects
 * whether the capability is enabled; this class only draws and maps native
 * pointer coordinates to the host's current content range.
 */
internal class InteractiveScrollbar(
    density: Float,
    private val vertical: Boolean,
) {
    private val edgeMargin = 4f * density
    private val mainMargin = 4f * density
    private val trackWidth = 3f * density
    private val thumbWidth = INTERACTIVE_SCROLLBAR_VISUAL_THICKNESS_DP * density
    private val touchTarget = INTERACTIVE_SCROLLBAR_TOUCH_TARGET_DP * density
    private val minimumThumbExtent = INTERACTIVE_SCROLLBAR_MIN_THUMB_DP * density
    private val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(72, 15, 23, 42)
    }
    private val thumbPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(37, 99, 235)
    }
    private var grabbedAt = 0f
    private var activePointerId = MotionEvent.INVALID_POINTER_ID
    // Reused production geometry. The pure fixture reference returns an
    // immutable value, but drawing and dragging do not allocate per frame.
    private var currentTrackStart = 0f
    private var currentTrackExtent = 0f
    private var currentThumbStart = 0f
    private var currentThumbExtent = 0f
    private var currentMaxScroll = 0f

    var enabled: Boolean = false
        private set
    var dragging: Boolean = false
        private set

    fun setEnabled(value: Boolean) {
        enabled = value
        if (!value) finishDrag()
    }

    fun tryStartDrag(
        event: MotionEvent,
        mainExtent: Int,
        crossExtent: Int,
        paddingStart: Int,
        paddingEnd: Int,
        viewportExtent: Int,
        scrollOffset: Int,
        maxScroll: Int,
    ): Boolean {
        val pointerIndex = event.actionIndex
        if (
            !enabled || maxScroll <= 0 || pointerIndex !in 0 until event.pointerCount ||
            !insideTouchTarget(event, pointerIndex, crossExtent)
        ) return false
        if (!updateGeometry(
                mainExtent,
                paddingStart,
                paddingEnd,
                viewportExtent,
                scrollOffset,
                maxScroll,
            )) return false
        activePointerId = event.getPointerId(pointerIndex)
        grabbedAt = InteractiveScrollbarMath.grabOffset(
            mainPosition(event, pointerIndex),
            currentThumbStart,
            currentThumbExtent,
        )
        dragging = true
        return true
    }

    fun targetForDrag(
        event: MotionEvent,
        mainExtent: Int,
        paddingStart: Int,
        paddingEnd: Int,
        viewportExtent: Int,
        scrollOffset: Int,
        maxScroll: Int,
    ): Int? {
        if (!enabled || !dragging) return null
        val pointerIndex = event.findPointerIndex(activePointerId)
        if (pointerIndex < 0) {
            finishDrag()
            return null
        }
        if (!updateGeometry(
                mainExtent,
                paddingStart,
                paddingEnd,
                viewportExtent,
                scrollOffset,
                maxScroll,
            )) return null
        return InteractiveScrollbarMath.targetOffset(
            mainPosition(event, pointerIndex),
            grabbedAt,
            currentTrackStart,
            currentTrackExtent,
            currentThumbExtent,
            currentMaxScroll,
        )
    }

    fun activePointerIsGoingUp(event: MotionEvent): Boolean =
        dragging && event.actionMasked == MotionEvent.ACTION_POINTER_UP &&
            event.actionIndex in 0 until event.pointerCount &&
            event.getPointerId(event.actionIndex) == activePointerId

    fun finishDrag() {
        dragging = false
        grabbedAt = 0f
        activePointerId = MotionEvent.INVALID_POINTER_ID
    }

    fun draw(
        canvas: Canvas,
        viewportOriginX: Float,
        viewportOriginY: Float,
        width: Int,
        height: Int,
        paddingStart: Int,
        paddingEnd: Int,
        viewportExtent: Int,
        scrollOffset: Int,
        maxScroll: Int,
    ) {
        if (!enabled || maxScroll <= 0) return
        val mainExtent = if (vertical) height else width
        if (!updateGeometry(
                mainExtent,
                paddingStart,
                paddingEnd,
                viewportExtent,
                scrollOffset,
                maxScroll,
            )) return
        val trackRadius = trackWidth / 2f
        val thumbRadius = thumbWidth / 2f
        if (vertical) {
            val centerX = viewportOriginX + width - edgeMargin - thumbWidth / 2f
            canvas.drawRoundRect(
                centerX - trackWidth / 2f,
                viewportOriginY + currentTrackStart,
                centerX + trackWidth / 2f,
                viewportOriginY + currentTrackStart + currentTrackExtent,
                trackRadius,
                trackRadius,
                trackPaint,
            )
            canvas.drawRoundRect(
                centerX - thumbWidth / 2f,
                viewportOriginY + currentThumbStart,
                centerX + thumbWidth / 2f,
                viewportOriginY + currentThumbStart + currentThumbExtent,
                thumbRadius,
                thumbRadius,
                thumbPaint,
            )
        } else {
            val centerY = viewportOriginY + height - edgeMargin - thumbWidth / 2f
            canvas.drawRoundRect(
                viewportOriginX + currentTrackStart,
                centerY - trackWidth / 2f,
                viewportOriginX + currentTrackStart + currentTrackExtent,
                centerY + trackWidth / 2f,
                trackRadius,
                trackRadius,
                trackPaint,
            )
            canvas.drawRoundRect(
                viewportOriginX + currentThumbStart,
                centerY - thumbWidth / 2f,
                viewportOriginX + currentThumbStart + currentThumbExtent,
                centerY + thumbWidth / 2f,
                thumbRadius,
                thumbRadius,
                thumbPaint,
            )
        }
    }

    private fun updateGeometry(
        mainExtent: Int,
        paddingStart: Int,
        paddingEnd: Int,
        viewportExtent: Int,
        scrollOffset: Int,
        maxScroll: Int,
    ): Boolean {
        currentTrackStart = paddingStart.toFloat() + mainMargin
        currentTrackExtent = (
            mainExtent - paddingStart - paddingEnd - mainMargin * 2f
        ).coerceAtLeast(0f)
        if (currentTrackExtent <= 0f || viewportExtent <= 0 || maxScroll <= 0) {
            return false
        }
        currentMaxScroll = maxScroll.toFloat()
        val contentExtent = (maxScroll + viewportExtent).toFloat()
        currentThumbExtent = (
            currentTrackExtent * viewportExtent / contentExtent
        ).coerceIn(minimumThumbExtent.coerceAtMost(currentTrackExtent), currentTrackExtent)
        val travel = currentTrackExtent - currentThumbExtent
        val fraction = (scrollOffset / currentMaxScroll).coerceIn(0f, 1f)
        currentThumbStart = currentTrackStart + travel * fraction
        return true
    }

    private fun insideTouchTarget(
        event: MotionEvent,
        pointerIndex: Int,
        crossExtent: Int,
    ): Boolean {
        val cross = if (vertical) event.getX(pointerIndex) else event.getY(pointerIndex)
        return cross >= crossExtent - touchTarget && cross <= crossExtent.toFloat()
    }

    private fun mainPosition(event: MotionEvent, pointerIndex: Int): Float =
        if (vertical) event.getY(pointerIndex) else event.getX(pointerIndex)
}
