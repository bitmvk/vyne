package dev.vyne

import android.content.Context
import android.graphics.Canvas
import android.graphics.Path
import android.os.SystemClock
import android.view.MotionEvent
import android.view.VelocityTracker
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.OverScroller
import android.widget.ScrollView

/**
 * ViewGroup subclasses that clip children to rounded corners via `dispatchDraw`.
 *
 * Android's `View.clipToOutline` only clips the View's own background — it does
 * NOT clip child views.  To get true rounded-corner clipping of content, we
 * must override `dispatchDraw` and apply a canvas clip before drawing children.
 * This is the same pattern React Native uses in ReactViewGroup.
 *
 * The canvas clip is controlled by `clipsChildrenToBounds` (which follows the
 * `overflow` prop from Python).  When overflow is "visible", clipping is
 * disabled so shadows and positioned children can extend outside the bounds.
 */

/** Shared dispatchDraw clipping logic. */
private fun applyChildClip(
    canvas: Canvas,
    view: View,
    radii: Renderer.CornerRadii?,
    clipPath: Path,
    clipsChildrenToBounds: Boolean,
): Int? {
    if (!clipsChildrenToBounds) return null
    val r = radii ?: return null
    if (!r.hasRadius) return null
    val w = view.width.toFloat()
    val h = view.height.toFloat()
    if (w <= 0f || h <= 0f) return null
    clipPath.reset()
    clipPath.addRoundRect(0f, 0f, w, h, r.toPathRadii(), Path.Direction.CW)
    val checkpoint = canvas.save()
    canvas.clipPath(clipPath)
    return checkpoint
}

private fun restoreChildClip(canvas: Canvas, checkpoint: Int?) {
    if (checkpoint != null) canvas.restoreToCount(checkpoint)
}

/** Interface that the rounded ViewGroup subclasses implement. */
internal interface RoundedView {
    val clipPath: Path
    var cornerRadii: Renderer.CornerRadii?
    var clipsChildrenToBounds: Boolean
}

/**
 * Mechanical scroll operations used by virtual-list hosts.
 *
 * Python owns window selection; these hosts only report where the native
 * gesture is heading (`virtualListProjection`) and apply Python-driven
 * scroll targets.  Scrolling itself is never clamped here.
 */
internal interface VyneScrollContainer {
    val virtualListProjection: Pair<Int, Int>
    var interactiveScrollbarEnabled: Boolean
    fun setVirtualScrollSeekListener(listener: VirtualScrollSeekListener?)
    fun clearVirtualScrollSeekState()
    fun consumeSeekRevealMetricsSuppression(x: Int, y: Int, now: Long): Boolean
    fun setVirtualListInitialOffset(offset: Int)
    fun scrollToPosition(x: Int, y: Int)
    fun smoothScrollToPosition(x: Int, y: Int)
}

/**
 * A Python-driven scroll target that could not be applied yet because the
 * content had not reached the target's extent (e.g. the window commit that
 * grows the content is still being published).  Applied on the next layout.
 */
private data class PendingScroll(
    val x: Int,
    val y: Int,
    val animated: Boolean,
)

/**
 * Projects where the in-flight gesture will stop using native fling physics.
 *
 * The projection is the host's only list-specific state: a fling/drag target
 * expressed in pixels.  Python reads it from the `scroll_metrics` payload and
 * renders the window for that target ahead of time.
 */
private class VirtualListProjection(context: Context) {
    private val scroller = OverScroller(context)
    private val velocityTracker = VelocityTracker.obtain()
    private var trackingTouch = false
    var offsetX: Int = 0
        private set
    var offsetY: Int = 0
        private set

    /** A new gesture starts at the current position; the old target is stale. */
    fun beginGesture(owner: ViewGroup) {
        trackingTouch = true
        velocityTracker.clear()
        reset(owner.scrollX, owner.scrollY)
    }

    fun trackMove(owner: ViewGroup, event: MotionEvent) {
        if (!trackingTouch) return
        velocityTracker.addMovement(event)
        velocityTracker.computeCurrentVelocity(1000)
        // ScrollView flings with the negated tracker velocity (an upward
        // finger moves content up = positive scroll), so project with the
        // same sign convention.
        project(
            owner,
            -velocityTracker.xVelocity.toInt(),
            -velocityTracker.yVelocity.toInt(),
        )
    }

    fun endGesture() {
        trackingTouch = false
        velocityTracker.clear()
    }

    /** The native fling starts with exactly this velocity; mirror its landing. */
    fun fling(owner: ViewGroup, velocityX: Int, velocityY: Int) {
        project(owner, velocityX, velocityY)
    }

    /** Python asked to scroll here; treat the request as the projection. */
    fun target(x: Int, y: Int) {
        offsetX = x.coerceAtLeast(0)
        offsetY = y.coerceAtLeast(0)
    }

    private fun reset(x: Int, y: Int) {
        offsetX = x.coerceAtLeast(0)
        offsetY = y.coerceAtLeast(0)
    }

    private fun project(owner: ViewGroup, velocityX: Int, velocityY: Int) {
        val (maxX, maxY) = maxScroll(owner)
        scroller.fling(
            owner.scrollX,
            owner.scrollY,
            velocityX,
            velocityY,
            0,
            maxX,
            0,
            maxY,
        )
        offsetX = scroller.finalX
        offsetY = scroller.finalY
    }

    private fun maxScroll(owner: ViewGroup): Pair<Int, Int> {
        val content = owner.getChildAt(0)
        val viewportX =
            (owner.width - owner.paddingLeft - owner.paddingRight).coerceAtLeast(0)
        val viewportY =
            (owner.height - owner.paddingTop - owner.paddingBottom).coerceAtLeast(0)
        val maxX = ((content?.width ?: 0) - viewportX).coerceAtLeast(0)
        val maxY = ((content?.height ?: 0) - viewportY).coerceAtLeast(0)
        return maxX to maxY
    }
}

// ── RoundedFrameLayout ────────────────────────────────────────────

internal class RoundedFrameLayout(context: Context) :
    FrameLayout(context), RoundedView, MaxConstrainedView,
    VirtualStickyCell, VirtualStickyContent {

    override var vyneMaxWidthPx: Int = 0
    override var vyneMaxHeightPx: Int = 0
    override val clipPath = Path()
    override var cornerRadii: Renderer.CornerRadii? = null
    override var clipsChildrenToBounds: Boolean = true

    // Platform-neutral positioned-content extent (raw px). A ScrollView may
    // measure its child with an UNSPECIFIED main axis; enforce Python's
    // semantic extent without exposing an Android sentinel in the tree.
    var virtualContentWidthPx: Int = 0
        internal set
    var virtualContentHeightPx: Int = 0
        internal set

    // Virtual-list sticky state (raw px).  Ordinary Boxes keep defaults and
    // are never touched: the marker gates the native traversal, and sticky
    // fields are set only by the private list metadata props.
    override var isVirtualContent: Boolean = false
        internal set
    override var stickyEdge: String? = null
        internal set
    override var stickyBoundaryStartPx: Float = 0f
        internal set
    override var stickyBoundaryEndPx: Float = 0f
        internal set
    override var naturalTranslationX: Float = 0f
        internal set
    override var naturalTranslationY: Float = 0f
        internal set
    override val widthPx: Float get() = width.toFloat()
    override val heightPx: Float get() = height.toFloat()

    override val cellCount: Int get() = childCount
    override fun cellAt(index: Int): VirtualStickyCell? =
        getChildAt(index) as? VirtualStickyCell

    override var stickyViewportStart: Float = 0f
    override var stickyViewportEnd: Float = 0f
    override var stickyVertical: Boolean = false

    override fun applyStickyPosition(
        vertical: Boolean,
        main: Float,
        displaced: Boolean,
    ) {
        if (vertical) {
            if (translationY != main) translationY = main
        } else {
            if (translationX != main) translationX = main
        }
        // A displaced sticky paints above ordinary cells; reset without
        // touching the user's elevation prop.
        val z = if (displaced) STICKY_Z_PX else 0f
        if (translationZ != z) translationZ = z
    }

    /**
     * Restore the natural placed position when sticky metadata is removed.
     *
     * Resets both translation axes and the paint Z; used when a cell loses
     * its sticky edge entirely or its content Box stops being virtual
     * content.  Per-axis removals use `resetNaturalX`/`resetNaturalY` so an
     * active displacement on the other axis is preserved.
     */
    override fun restoreNaturalPosition() {
        if (translationX != naturalTranslationX) translationX = naturalTranslationX
        if (translationY != naturalTranslationY) translationY = naturalTranslationY
        if (translationZ != 0f) translationZ = 0f
    }

    /**
     * Reset only the X axis (natural and visible), then re-apply any active
     * sticky displacement.  The Y axis and its displacement are untouched.
     */
    fun resetNaturalX() {
        naturalTranslationX = 0f
        if (translationX != 0f) translationX = 0f
        refreshSticky()
    }

    /**
     * Reset only the Y axis (natural and visible), then re-apply any active
     * sticky displacement.  The X axis and its displacement are untouched.
     */
    fun resetNaturalY() {
        naturalTranslationY = 0f
        if (translationY != 0f) translationY = 0f
        refreshSticky()
    }

    /**
     * Restore every direct cell wrapper to its natural position.  Runs when
     * the virtual-content marker is removed so no child stays displaced.
     */
    fun restoreChildrenNatural() {
        restoreVirtualContent(this)
    }

    /**
     * Re-apply the sticky displacement after a natural-translation prop
     * update, using the viewport the host last published to the content Box.
     * No-op until the wrapper is attached under a marked content Box.
     */
    fun refreshSticky() {
        if (stickyEdge == null) return
        val content = parent as? VirtualStickyContent ?: return
        if (!content.isVirtualContent) return
        val vertical = content.stickyVertical
        val natural = if (vertical) naturalTranslationY else naturalTranslationX
        val extent = if (vertical) height.toFloat() else width.toFloat()
        val target = computeStickyMain(
            natural,
            extent,
            content.stickyViewportStart,
            content.stickyViewportEnd,
            stickyBoundaryStartPx,
            stickyBoundaryEndPx,
            stickyEdge,
        )
        applyStickyPosition(vertical, target, target != natural)
    }

    override fun dispatchDraw(canvas: Canvas) {
        val checkpoint = applyChildClip(
            canvas, this, cornerRadii, clipPath, clipsChildrenToBounds
        )
        super.dispatchDraw(canvas)
        restoreChildClip(canvas, checkpoint)
    }
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec)
        val semanticWidth = maxOf(measuredWidth, virtualContentWidthPx)
        val semanticHeight = maxOf(measuredHeight, virtualContentHeightPx)
        val resolvedWidth = View.resolveSize(semanticWidth, widthMeasureSpec)
        val resolvedHeight = View.resolveSize(semanticHeight, heightMeasureSpec)
        val (w, h) = constrainMeasured(resolvedWidth, resolvedHeight)
        setMeasuredDimension(w, h)
    }

}

// ── RoundedLinearLayout ───────────────────────────────────────────

internal class RoundedLinearLayout(context: Context) : LinearLayout(context), RoundedView, MaxConstrainedView {

    override var vyneMaxWidthPx: Int = 0
    override var vyneMaxHeightPx: Int = 0
    override val clipPath = Path()
    override var cornerRadii: Renderer.CornerRadii? = null
    override var clipsChildrenToBounds: Boolean = true
    var alignItems: String? = null
    var justifyContent: String? = null

    override fun dispatchDraw(canvas: Canvas) {
        val checkpoint = applyChildClip(
            canvas, this, cornerRadii, clipPath, clipsChildrenToBounds
        )
        super.dispatchDraw(canvas)
        restoreChildClip(canvas, checkpoint)
    }
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec)
        val (w, h) = constrainMeasured(measuredWidth, measuredHeight)
        setMeasuredDimension(w, h)
    }

}

/**
 * Refresh sticky cell positions for one virtual-list scroll host.
 *
 * Gated on the marked direct content Box, so ordinary Scroll views pay
 * nothing.  Loops only over realized direct children (O(realized)) and
 * publishes the current viewport to the content so prop updates can
 * re-displace immediately.
 */
private fun updateVirtualSticky(host: ViewGroup) {
    val content = host.getChildAt(0) as? VirtualStickyContent ?: return
    if (!content.isVirtualContent) return
    val vertical = host is RoundedScrollView
    val viewportStart = if (vertical) host.scrollY else host.scrollX
    val viewportExtent = if (vertical) {
        (host.height - host.paddingTop - host.paddingBottom).coerceAtLeast(0)
    } else {
        (host.width - host.paddingLeft - host.paddingRight).coerceAtLeast(0)
    }
    val viewportEnd = viewportStart + viewportExtent
    content.stickyViewportStart = viewportStart.toFloat()
    content.stickyViewportEnd = viewportEnd.toFloat()
    content.stickyVertical = vertical
    updateStickyContent(content, viewportStart.toFloat(), viewportEnd.toFloat(), vertical)
}

// ── RoundedScrollView ─────────────────────────────────────────────

internal class RoundedScrollView(context: Context) :
    ScrollView(context), RoundedView, MaxConstrainedView, VyneScrollContainer {

    private val projection = VirtualListProjection(context)
    private val interactiveScrollbar = InteractiveScrollbar(
        context.resources.displayMetrics.density,
        vertical = true,
    )
    private val virtualSeek = VirtualScrollSeekHostState(vertical = true)
    private val virtualSeekWatchdog = Runnable { runVirtualSeekWatchdog() }
    private var pendingInitialOffset: Int? = null
    private var pendingScroll: PendingScroll? = null

    override var vyneMaxWidthPx: Int = 0
    override var vyneMaxHeightPx: Int = 0
    override val clipPath = Path()
    override var cornerRadii: Renderer.CornerRadii? = null
    override var clipsChildrenToBounds: Boolean = true

    override val virtualListProjection: Pair<Int, Int>
        get() = projection.offsetX to projection.offsetY

    override var interactiveScrollbarEnabled: Boolean
        get() = interactiveScrollbar.enabled
        set(value) {
            // Candidate prop removal can still roll back. Renderer clears
            // seek state only after accepted disable/removal.
            if (!value) finishInteractiveScrollbarDrag(resetSeek = false)
            interactiveScrollbar.setEnabled(value)
            isVerticalScrollBarEnabled = !value
            invalidate()
        }

    override fun setVirtualScrollSeekListener(listener: VirtualScrollSeekListener?) {
        // Candidate listener mutation can still roll back. Preserve state
        // until Renderer confirms accepted removal.
        virtualSeek.setListener(listener)
        invalidate()
    }

    override fun clearVirtualScrollSeekState() {
        removeCallbacks(virtualSeekWatchdog)
        virtualSeek.reset()
        invalidate()
    }

    override fun consumeSeekRevealMetricsSuppression(
        x: Int,
        y: Int,
        now: Long,
    ): Boolean = virtualSeek.consumeMetricsSuppression(x, y, now)

    internal val interactiveScrollbarDraggingForTest: Boolean
        get() = interactiveScrollbar.dragging
    internal val interactiveScrollbarDisplayOffsetForTest: Int
        get() = virtualSeek.displayOffset(scrollY)

    override fun dispatchDraw(canvas: Canvas) {
        val checkpoint = applyChildClip(
            canvas, this, cornerRadii, clipPath, clipsChildrenToBounds
        )
        super.dispatchDraw(canvas)
        restoreChildClip(canvas, checkpoint)
        val maxY = maxScrollY()
        val viewportY = (height - paddingTop - paddingBottom).coerceAtLeast(0)
        interactiveScrollbar.draw(
            canvas,
            viewportOriginX = scrollX.toFloat(),
            viewportOriginY = scrollY.toFloat(),
            width = width,
            height = height,
            paddingStart = paddingTop,
            paddingEnd = paddingBottom,
            viewportExtent = viewportY,
            scrollOffset = virtualSeek.displayOffset(scrollY),
            maxScroll = maxY,
        )
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec)
        val (w, h) = constrainMeasured(measuredWidth, measuredHeight)
        setMeasuredDimension(w, h)
    }

    override fun onLayout(changed: Boolean, left: Int, top: Int, right: Int, bottom: Int) {
        super.onLayout(changed, left, top, right, bottom)
        pendingInitialOffset?.let { offset ->
            pendingInitialOffset = null
            scrollTo(0, offset)
        }
        pendingScroll?.let { pending ->
            val (maxX, maxY) = scrollBounds()
            val boundedX = pending.x.coerceIn(0, maxX)
            val boundedY = pending.y.coerceIn(0, maxY)
            pendingScroll = null
            if (pending.animated) {
                super.smoothScrollTo(boundedX, boundedY)
            } else {
                prepareSeekReveal(boundedX, boundedY)
                super.scrollTo(boundedX, boundedY)
            }
        }
        // Cells may have moved, entered, or left; refresh stickies with the
        // current viewport (no bridge event, no Python commit).
        updateVirtualSticky(this)
    }

    override fun onScrollChanged(l: Int, t: Int, oldl: Int, oldt: Int) {
        super.onScrollChanged(l, t, oldl, oldt)
        updateVirtualSticky(this)
    }

    private fun maxScrollY(): Int {
        val content = getChildAt(0)
        val viewportY =
            (height - paddingTop - paddingBottom).coerceAtLeast(0)
        return ((content?.height ?: 0) - viewportY).coerceAtLeast(0)
    }

    private fun scrollBounds(): Pair<Int, Int> = 0 to maxScrollY()

    override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            if (beginInteractiveScrollbarDrag(event)) {
                super.fling(0)
                projection.endGesture()
                parent?.requestDisallowInterceptTouchEvent(true)
                return true
            }
            super.fling(0)
            projection.beginGesture(this)
        }
        if (interactiveScrollbar.dragging) return true
        return super.onInterceptTouchEvent(event)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (interactiveScrollbar.dragging) {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE ->
                    updateInteractiveScrollbarDrag(event, final = false)
                MotionEvent.ACTION_POINTER_UP -> {
                    if (interactiveScrollbar.activePointerIsGoingUp(event)) {
                        updateInteractiveScrollbarDrag(event, final = true)
                        finishInteractiveScrollbarDrag()
                    }
                }
                MotionEvent.ACTION_UP -> {
                    updateInteractiveScrollbarDrag(event, final = true)
                    finishInteractiveScrollbarDrag()
                }
                MotionEvent.ACTION_CANCEL ->
                    finishInteractiveScrollbarDrag(resetSeek = true)
            }
            return true
        }
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                super.fling(0)
                projection.beginGesture(this)
            }
            MotionEvent.ACTION_MOVE -> projection.trackMove(this, event)
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> projection.endGesture()
        }
        return super.onTouchEvent(event)
    }

    private fun beginInteractiveScrollbarDrag(event: MotionEvent): Boolean {
        val maxY = maxScrollY()
        val viewportY = (height - paddingTop - paddingBottom).coerceAtLeast(0)
        val started = interactiveScrollbar.tryStartDrag(
            event,
            mainExtent = height,
            crossExtent = width,
            paddingStart = paddingTop,
            paddingEnd = paddingBottom,
            viewportExtent = viewportY,
            scrollOffset = scrollY,
            maxScroll = maxY,
        )
        if (started && virtualSeek.enabled) {
            removeCallbacks(virtualSeekWatchdog)
            virtualSeek.beginGesture()
        }
        return started
    }

    private fun updateInteractiveScrollbarDrag(event: MotionEvent, final: Boolean) {
        val maxY = maxScrollY()
        val viewportY = (height - paddingTop - paddingBottom).coerceAtLeast(0)
        val target = interactiveScrollbar.targetForDrag(
            event,
            mainExtent = height,
            paddingStart = paddingTop,
            paddingEnd = paddingBottom,
            viewportExtent = viewportY,
            scrollOffset = virtualSeek.displayOffset(scrollY),
            maxScroll = maxY,
        )
        if (target == null) {
            if (!interactiveScrollbar.dragging) {
                // Active pointer disappeared without a normal up/cancel.
                finishInteractiveScrollbarDrag(resetSeek = true)
            }
            return
        }
        if (virtualSeek.enabled) {
            virtualSeek.update(target, event.eventTime, final)
            if (final) scheduleVirtualSeekWatchdog()
            invalidate()
            return
        }
        pendingScroll = null
        projection.target(0, target)
        super.scrollTo(0, target)
        invalidate()
    }

    private fun scheduleVirtualSeekWatchdog() {
        removeCallbacks(virtualSeekWatchdog)
        if (virtualSeek.finalPending) {
            postDelayed(virtualSeekWatchdog, VIRTUAL_SCROLL_SEEK_WATCHDOG_MS)
        }
    }

    private fun runVirtualSeekWatchdog() {
        if (!virtualSeek.enabled) return
        virtualSeek.retry(scrollY, SystemClock.uptimeMillis())
        invalidate()
        scheduleVirtualSeekWatchdog()
    }

    private fun prepareSeekReveal(x: Int, y: Int) {
        // Accept even when rounding leaves the host at its current pixel; the
        // final watchdog must not retry an already satisfied target.
        if (virtualSeek.acceptReveal(x, y, SystemClock.uptimeMillis())) {
            if (!virtualSeek.finalPending) removeCallbacks(virtualSeekWatchdog)
        }
    }

    private fun finishInteractiveScrollbarDrag(resetSeek: Boolean = false) {
        interactiveScrollbar.finishDrag()
        parent?.requestDisallowInterceptTouchEvent(false)
        if (resetSeek) {
            removeCallbacks(virtualSeekWatchdog)
            virtualSeek.reset()
            invalidate()
        }
    }

    override fun fling(velocityY: Int) {
        super.fling(velocityY)
        projection.fling(this, 0, velocityY)
    }

    override fun setVirtualListInitialOffset(offset: Int) {
        // Full-tree publication sets root props before inserting its content.
        // Existing mounted lists already have a content child and must not be
        // pulled back to an older Python observation during normal scrolling.
        if (childCount > 0) return
        pendingInitialOffset = offset.coerceAtLeast(0)
        projection.target(0, offset.coerceAtLeast(0))
        requestLayout()
    }

    override fun scrollToPosition(x: Int, y: Int) {
        projection.target(x, y)
        applyOrDeferScroll(x, y, animated = false)
    }

    override fun smoothScrollToPosition(x: Int, y: Int) {
        projection.target(x, y)
        applyOrDeferScroll(x, y, animated = true)
    }

    private fun applyOrDeferScroll(x: Int, y: Int, animated: Boolean) {
        val (_, maxY) = scrollBounds()
        val boundedY = y.coerceIn(0, maxY)
        if (boundedY == y) {
            pendingScroll = null
            if (animated) {
                super.smoothScrollTo(x, y)
            } else {
                prepareSeekReveal(x, y)
                super.scrollTo(x, y)
            }
        } else {
            // The content is not laid out yet (or still shorter than the
            // target). ScrollView.scrollTo would clamp to the current max
            // and the scroll would be silently lost; retry after the next
            // layout pass once the published window is in place.
            pendingScroll = PendingScroll(x, y, animated)
            requestLayout()
        }
    }

    override fun onDetachedFromWindow() {
        finishInteractiveScrollbarDrag(resetSeek = true)
        projection.endGesture()
        super.onDetachedFromWindow()
    }
}

// ── RoundedHorizontalScrollView ───────────────────────────────────

internal class RoundedHorizontalScrollView(context: Context) :
    HorizontalScrollView(context), RoundedView, MaxConstrainedView, VyneScrollContainer {

    private val projection = VirtualListProjection(context)
    private val interactiveScrollbar = InteractiveScrollbar(
        context.resources.displayMetrics.density,
        vertical = false,
    )
    private val virtualSeek = VirtualScrollSeekHostState(vertical = false)
    private val virtualSeekWatchdog = Runnable { runVirtualSeekWatchdog() }
    private var pendingInitialOffset: Int? = null
    private var pendingScroll: PendingScroll? = null

    override var vyneMaxWidthPx: Int = 0
    override var vyneMaxHeightPx: Int = 0
    override val clipPath = Path()
    override var cornerRadii: Renderer.CornerRadii? = null
    override var clipsChildrenToBounds: Boolean = true

    override val virtualListProjection: Pair<Int, Int>
        get() = projection.offsetX to projection.offsetY

    override var interactiveScrollbarEnabled: Boolean
        get() = interactiveScrollbar.enabled
        set(value) {
            // Candidate prop removal can still roll back. Renderer clears
            // seek state only after accepted disable/removal.
            if (!value) finishInteractiveScrollbarDrag(resetSeek = false)
            interactiveScrollbar.setEnabled(value)
            isHorizontalScrollBarEnabled = !value
            invalidate()
        }

    override fun setVirtualScrollSeekListener(listener: VirtualScrollSeekListener?) {
        // Candidate listener mutation can still roll back. Preserve state
        // until Renderer confirms accepted removal.
        virtualSeek.setListener(listener)
        invalidate()
    }

    override fun clearVirtualScrollSeekState() {
        removeCallbacks(virtualSeekWatchdog)
        virtualSeek.reset()
        invalidate()
    }

    override fun consumeSeekRevealMetricsSuppression(
        x: Int,
        y: Int,
        now: Long,
    ): Boolean = virtualSeek.consumeMetricsSuppression(x, y, now)

    internal val interactiveScrollbarDraggingForTest: Boolean
        get() = interactiveScrollbar.dragging
    internal val interactiveScrollbarDisplayOffsetForTest: Int
        get() = virtualSeek.displayOffset(scrollX)

    override fun dispatchDraw(canvas: Canvas) {
        val checkpoint = applyChildClip(
            canvas, this, cornerRadii, clipPath, clipsChildrenToBounds
        )
        super.dispatchDraw(canvas)
        restoreChildClip(canvas, checkpoint)
        val maxX = maxScrollX()
        val viewportX = (width - paddingLeft - paddingRight).coerceAtLeast(0)
        interactiveScrollbar.draw(
            canvas,
            viewportOriginX = scrollX.toFloat(),
            viewportOriginY = scrollY.toFloat(),
            width = width,
            height = height,
            paddingStart = paddingLeft,
            paddingEnd = paddingRight,
            viewportExtent = viewportX,
            scrollOffset = virtualSeek.displayOffset(scrollX),
            maxScroll = maxX,
        )
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec)
        val (w, h) = constrainMeasured(measuredWidth, measuredHeight)
        setMeasuredDimension(w, h)
    }

    override fun onLayout(changed: Boolean, left: Int, top: Int, right: Int, bottom: Int) {
        super.onLayout(changed, left, top, right, bottom)
        pendingInitialOffset?.let { offset ->
            pendingInitialOffset = null
            scrollTo(offset, 0)
        }
        pendingScroll?.let { pending ->
            val (maxX, maxY) = scrollBounds()
            val boundedX = pending.x.coerceIn(0, maxX)
            val boundedY = pending.y.coerceIn(0, maxY)
            pendingScroll = null
            if (pending.animated) {
                super.smoothScrollTo(boundedX, boundedY)
            } else {
                prepareSeekReveal(boundedX, boundedY)
                super.scrollTo(boundedX, boundedY)
            }
        }
        // Cells may have moved, entered, or left; refresh stickies with the
        // current viewport (no bridge event, no Python commit).
        updateVirtualSticky(this)
    }

    override fun onScrollChanged(l: Int, t: Int, oldl: Int, oldt: Int) {
        super.onScrollChanged(l, t, oldl, oldt)
        updateVirtualSticky(this)
    }

    private fun maxScrollX(): Int {
        val content = getChildAt(0)
        val viewportX =
            (width - paddingLeft - paddingRight).coerceAtLeast(0)
        return ((content?.width ?: 0) - viewportX).coerceAtLeast(0)
    }

    private fun scrollBounds(): Pair<Int, Int> = maxScrollX() to 0

    override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            if (beginInteractiveScrollbarDrag(event)) {
                super.fling(0)
                projection.endGesture()
                parent?.requestDisallowInterceptTouchEvent(true)
                return true
            }
            super.fling(0)
            projection.beginGesture(this)
        }
        if (interactiveScrollbar.dragging) return true
        return super.onInterceptTouchEvent(event)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (interactiveScrollbar.dragging) {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE ->
                    updateInteractiveScrollbarDrag(event, final = false)
                MotionEvent.ACTION_POINTER_UP -> {
                    if (interactiveScrollbar.activePointerIsGoingUp(event)) {
                        updateInteractiveScrollbarDrag(event, final = true)
                        finishInteractiveScrollbarDrag()
                    }
                }
                MotionEvent.ACTION_UP -> {
                    updateInteractiveScrollbarDrag(event, final = true)
                    finishInteractiveScrollbarDrag()
                }
                MotionEvent.ACTION_CANCEL ->
                    finishInteractiveScrollbarDrag(resetSeek = true)
            }
            return true
        }
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                super.fling(0)
                projection.beginGesture(this)
            }
            MotionEvent.ACTION_MOVE -> projection.trackMove(this, event)
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> projection.endGesture()
        }
        return super.onTouchEvent(event)
    }

    private fun beginInteractiveScrollbarDrag(event: MotionEvent): Boolean {
        val maxX = maxScrollX()
        val viewportX = (width - paddingLeft - paddingRight).coerceAtLeast(0)
        val started = interactiveScrollbar.tryStartDrag(
            event,
            mainExtent = width,
            crossExtent = height,
            paddingStart = paddingLeft,
            paddingEnd = paddingRight,
            viewportExtent = viewportX,
            scrollOffset = scrollX,
            maxScroll = maxX,
        )
        if (started && virtualSeek.enabled) {
            removeCallbacks(virtualSeekWatchdog)
            virtualSeek.beginGesture()
        }
        return started
    }

    private fun updateInteractiveScrollbarDrag(event: MotionEvent, final: Boolean) {
        val maxX = maxScrollX()
        val viewportX = (width - paddingLeft - paddingRight).coerceAtLeast(0)
        val target = interactiveScrollbar.targetForDrag(
            event,
            mainExtent = width,
            paddingStart = paddingLeft,
            paddingEnd = paddingRight,
            viewportExtent = viewportX,
            scrollOffset = virtualSeek.displayOffset(scrollX),
            maxScroll = maxX,
        )
        if (target == null) {
            if (!interactiveScrollbar.dragging) {
                // Active pointer disappeared without a normal up/cancel.
                finishInteractiveScrollbarDrag(resetSeek = true)
            }
            return
        }
        if (virtualSeek.enabled) {
            virtualSeek.update(target, event.eventTime, final)
            if (final) scheduleVirtualSeekWatchdog()
            invalidate()
            return
        }
        pendingScroll = null
        projection.target(target, 0)
        super.scrollTo(target, 0)
        invalidate()
    }

    private fun scheduleVirtualSeekWatchdog() {
        removeCallbacks(virtualSeekWatchdog)
        if (virtualSeek.finalPending) {
            postDelayed(virtualSeekWatchdog, VIRTUAL_SCROLL_SEEK_WATCHDOG_MS)
        }
    }

    private fun runVirtualSeekWatchdog() {
        if (!virtualSeek.enabled) return
        virtualSeek.retry(scrollX, SystemClock.uptimeMillis())
        invalidate()
        scheduleVirtualSeekWatchdog()
    }

    private fun prepareSeekReveal(x: Int, y: Int) {
        // Accept even when rounding leaves the host at its current pixel; the
        // final watchdog must not retry an already satisfied target.
        if (virtualSeek.acceptReveal(x, y, SystemClock.uptimeMillis())) {
            if (!virtualSeek.finalPending) removeCallbacks(virtualSeekWatchdog)
        }
    }

    private fun finishInteractiveScrollbarDrag(resetSeek: Boolean = false) {
        interactiveScrollbar.finishDrag()
        parent?.requestDisallowInterceptTouchEvent(false)
        if (resetSeek) {
            removeCallbacks(virtualSeekWatchdog)
            virtualSeek.reset()
            invalidate()
        }
    }

    override fun fling(velocityX: Int) {
        super.fling(velocityX)
        projection.fling(this, velocityX, 0)
    }

    override fun setVirtualListInitialOffset(offset: Int) {
        if (childCount > 0) return
        pendingInitialOffset = offset.coerceAtLeast(0)
        projection.target(offset.coerceAtLeast(0), 0)
        requestLayout()
    }

    override fun scrollToPosition(x: Int, y: Int) {
        projection.target(x, y)
        applyOrDeferScroll(x, y, animated = false)
    }

    override fun smoothScrollToPosition(x: Int, y: Int) {
        projection.target(x, y)
        applyOrDeferScroll(x, y, animated = true)
    }

    private fun applyOrDeferScroll(x: Int, y: Int, animated: Boolean) {
        val (maxX, _) = scrollBounds()
        val boundedX = x.coerceIn(0, maxX)
        if (boundedX == x) {
            pendingScroll = null
            if (animated) {
                super.smoothScrollTo(x, y)
            } else {
                prepareSeekReveal(x, y)
                super.scrollTo(x, y)
            }
        } else {
            // Content not laid out yet; retry after the next layout pass.
            pendingScroll = PendingScroll(x, y, animated)
            requestLayout()
        }
    }

    override fun onDetachedFromWindow() {
        finishInteractiveScrollbarDrag(resetSeek = true)
        projection.endGesture()
        super.onDetachedFromWindow()
    }
}
