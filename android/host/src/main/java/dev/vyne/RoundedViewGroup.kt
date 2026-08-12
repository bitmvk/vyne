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
    val left = view.scrollX.toFloat()
    val top = view.scrollY.toFloat()
    clipPath.reset()
    clipPath.addRoundRect(left, top, left + w, top + h, r.toPathRadii(), Path.Direction.CW)
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
private fun updateVirtualSticky(host: ViewGroup, vertical: Boolean) {
    val content = host.getChildAt(0) as? VirtualStickyContent ?: return
    if (!content.isVirtualContent) return
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

/**
 * Axis-aware scroll mechanics shared by the vertical and horizontal
 * virtual-list hosts.
 *
 * Owns the projection, interactive scrollbar, seek state, and pending-scroll
 * bookkeeping; the host View supplies the platform calls (`super.fling` etc.)
 * and delegates everything else here.  The `vertical` flag selects the main
 * axis for every measurement and target mapping.
 */
private class ScrollHostMechanics(
    context: Context,
    private val vertical: Boolean,
    private val owner: ViewGroup,
    // ScrollView/HorizontalScrollView expose smoothScrollTo; View does not,
    // so the host supplies its own platform call.
    private val animateScrollTo: (x: Int, y: Int) -> Unit,
) {
    private val projection = VirtualListProjection(context)
    private val interactiveScrollbar = InteractiveScrollbar(
        context.resources.displayMetrics.density,
        vertical = vertical,
    )
    private val virtualSeek = VirtualScrollSeekHostState(vertical = vertical)
    private val virtualSeekWatchdog = Runnable { runVirtualSeekWatchdog() }
    private var pendingInitialOffset: Int? = null
    private var pendingScroll: PendingScroll? = null

    private val scrollOffset: Int
        get() = if (vertical) owner.scrollY else owner.scrollX
    private val paddingStart: Int
        get() = if (vertical) owner.paddingTop else owner.paddingLeft
    private val paddingEnd: Int
        get() = if (vertical) owner.paddingBottom else owner.paddingRight
    private val mainExtent: Int
        get() = if (vertical) owner.height else owner.width
    private val crossExtent: Int
        get() = if (vertical) owner.width else owner.height

    val virtualListProjection: Pair<Int, Int>
        get() = projection.offsetX to projection.offsetY

    val dragging: Boolean
        get() = interactiveScrollbar.dragging

    val draggingForTest: Boolean
        get() = dragging

    fun displayOffsetForTest(): Int = virtualSeek.displayOffset(scrollOffset)

    var interactiveScrollbarEnabled: Boolean
        get() = interactiveScrollbar.enabled
        set(value) {
            // Candidate prop removal can still roll back. Renderer clears
            // seek state only after accepted disable/removal.
            if (!value) finishInteractiveScrollbarDrag(resetSeek = false)
            interactiveScrollbar.setEnabled(value)
            if (vertical) owner.isVerticalScrollBarEnabled = !value
            else owner.isHorizontalScrollBarEnabled = !value
            owner.invalidate()
        }

    fun setVirtualScrollSeekListener(listener: VirtualScrollSeekListener?) {
        // Candidate listener mutation can still roll back. Preserve state
        // until Renderer confirms accepted removal.
        virtualSeek.setListener(listener)
        owner.invalidate()
    }

    fun clearVirtualScrollSeekState() {
        owner.removeCallbacks(virtualSeekWatchdog)
        virtualSeek.reset()
        owner.invalidate()
    }

    fun consumeSeekRevealMetricsSuppression(x: Int, y: Int, now: Long): Boolean =
        virtualSeek.consumeMetricsSuppression(x, y, now)

    fun drawScrollbar(canvas: Canvas) {
        val max = maxScroll()
        val viewport = (mainExtent - paddingStart - paddingEnd).coerceAtLeast(0)
        interactiveScrollbar.draw(
            canvas,
            viewportOriginX = owner.scrollX.toFloat(),
            viewportOriginY = owner.scrollY.toFloat(),
            width = owner.width,
            height = owner.height,
            paddingStart = paddingStart,
            paddingEnd = paddingEnd,
            viewportExtent = viewport,
            scrollOffset = virtualSeek.displayOffset(scrollOffset),
            maxScroll = max,
        )
    }

    fun onLayoutCompleted() {
        pendingInitialOffset?.let { offset ->
            pendingInitialOffset = null
            owner.scrollTo(if (vertical) 0 else offset, if (vertical) offset else 0)
        }
        pendingScroll?.let { pending ->
            val max = maxScroll()
            val boundedX = if (vertical) 0 else pending.x.coerceIn(0, max)
            val boundedY = if (vertical) pending.y.coerceIn(0, max) else 0
            pendingScroll = null
            if (pending.animated) {
                animateScrollTo(boundedX, boundedY)
            } else {
                prepareSeekReveal(boundedX, boundedY)
                owner.scrollTo(boundedX, boundedY)
            }
        }
        // Cells may have moved, entered, or left; refresh stickies with the
        // current viewport (no bridge event, no Python commit).
        updateVirtualSticky(owner, vertical)
    }

    fun onScrollChanged() {
        updateVirtualSticky(owner, vertical)
    }

    private fun maxScroll(): Int {
        val content = owner.getChildAt(0)
        val viewport = (mainExtent - paddingStart - paddingEnd).coerceAtLeast(0)
        val extent = if (vertical) content?.height ?: 0 else content?.width ?: 0
        return (extent - viewport).coerceAtLeast(0)
    }

    fun beginGesture() {
        projection.beginGesture(owner)
    }

    fun endGesture() {
        projection.endGesture()
    }

    fun trackMove(event: MotionEvent) {
        projection.trackMove(owner, event)
    }

    fun projectFling(velocityX: Int, velocityY: Int) {
        projection.fling(owner, velocityX, velocityY)
    }

    fun setVirtualListInitialOffset(offset: Int) {
        // Full-tree publication sets root props before inserting its content.
        // Existing mounted lists already have a content child and must not be
        // pulled back to an older Python observation during normal scrolling.
        if (owner.childCount > 0) return
        pendingInitialOffset = offset.coerceAtLeast(0)
        projection.target(
            if (vertical) 0 else offset.coerceAtLeast(0),
            if (vertical) offset.coerceAtLeast(0) else 0,
        )
        owner.requestLayout()
    }

    fun scrollToPosition(x: Int, y: Int) {
        projection.target(x, y)
        applyOrDeferScroll(x, y, animated = false)
    }

    fun smoothScrollToPosition(x: Int, y: Int) {
        projection.target(x, y)
        applyOrDeferScroll(x, y, animated = true)
    }

    private fun applyOrDeferScroll(x: Int, y: Int, animated: Boolean) {
        val max = maxScroll()
        val target = if (vertical) y else x
        val bounded = target.coerceIn(0, max)
        if (bounded == target) {
            pendingScroll = null
            if (animated) {
                animateScrollTo(x, y)
            } else {
                prepareSeekReveal(x, y)
                owner.scrollTo(x, y)
            }
        } else {
            // The content is not laid out yet (or still shorter than the
            // target). ScrollView.scrollTo would clamp to the current max
            // and the scroll would be silently lost; retry after the next
            // layout pass once the published window is in place.
            pendingScroll = PendingScroll(x, y, animated)
            owner.requestLayout()
        }
    }

    fun beginInteractiveScrollbarDrag(event: MotionEvent): Boolean {
        val max = maxScroll()
        val viewport = (mainExtent - paddingStart - paddingEnd).coerceAtLeast(0)
        val started = interactiveScrollbar.tryStartDrag(
            event,
            mainExtent = mainExtent,
            crossExtent = crossExtent,
            paddingStart = paddingStart,
            paddingEnd = paddingEnd,
            viewportExtent = viewport,
            scrollOffset = scrollOffset,
            maxScroll = max,
        )
        if (started && virtualSeek.enabled) {
            owner.removeCallbacks(virtualSeekWatchdog)
            virtualSeek.beginGesture()
        }
        return started
    }

    fun updateInteractiveScrollbarDrag(event: MotionEvent, final: Boolean) {
        val max = maxScroll()
        val viewport = (mainExtent - paddingStart - paddingEnd).coerceAtLeast(0)
        val target = interactiveScrollbar.targetForDrag(
            event,
            mainExtent = mainExtent,
            paddingStart = paddingStart,
            paddingEnd = paddingEnd,
            viewportExtent = viewport,
            scrollOffset = virtualSeek.displayOffset(scrollOffset),
            maxScroll = max,
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
            owner.invalidate()
            return
        }
        pendingScroll = null
        projection.target(
            if (vertical) 0 else target,
            if (vertical) target else 0,
        )
        owner.scrollTo(if (vertical) 0 else target, if (vertical) target else 0)
        owner.invalidate()
    }

    fun activePointerIsGoingUp(event: MotionEvent): Boolean =
        interactiveScrollbar.activePointerIsGoingUp(event)

    fun finishInteractiveScrollbarDrag(resetSeek: Boolean = false) {
        interactiveScrollbar.finishDrag()
        owner.parent?.requestDisallowInterceptTouchEvent(false)
        if (resetSeek) {
            owner.removeCallbacks(virtualSeekWatchdog)
            virtualSeek.reset()
            owner.invalidate()
        }
    }

    fun onDetachedFromWindow() {
        finishInteractiveScrollbarDrag(resetSeek = true)
        projection.endGesture()
    }

    private fun scheduleVirtualSeekWatchdog() {
        owner.removeCallbacks(virtualSeekWatchdog)
        if (virtualSeek.finalPending) {
            owner.postDelayed(virtualSeekWatchdog, VIRTUAL_SCROLL_SEEK_WATCHDOG_MS)
        }
    }

    private fun runVirtualSeekWatchdog() {
        if (!virtualSeek.enabled) return
        virtualSeek.retry(scrollOffset, SystemClock.uptimeMillis())
        owner.invalidate()
        scheduleVirtualSeekWatchdog()
    }

    private fun prepareSeekReveal(x: Int, y: Int) {
        // Accept even when rounding leaves the host at its current pixel; the
        // final watchdog must not retry an already satisfied target.
        if (virtualSeek.acceptReveal(x, y, SystemClock.uptimeMillis())) {
            if (!virtualSeek.finalPending) owner.removeCallbacks(virtualSeekWatchdog)
        }
    }
}

// ── RoundedScrollView ─────────────────────────────────────────────

internal class RoundedScrollView(context: Context) :
    ScrollView(context), RoundedView, MaxConstrainedView, VyneScrollContainer {

    private val mechanics = ScrollHostMechanics(
        context,
        vertical = true,
        owner = this,
        animateScrollTo = { x, y -> smoothScrollTo(x, y) },
    )

    override var vyneMaxWidthPx: Int = 0
    override var vyneMaxHeightPx: Int = 0
    override val clipPath = Path()
    override var cornerRadii: Renderer.CornerRadii? = null
    override var clipsChildrenToBounds: Boolean = true

    override val virtualListProjection: Pair<Int, Int>
        get() = mechanics.virtualListProjection

    override var interactiveScrollbarEnabled: Boolean
        get() = mechanics.interactiveScrollbarEnabled
        set(value) {
            mechanics.interactiveScrollbarEnabled = value
        }

    override fun setVirtualScrollSeekListener(listener: VirtualScrollSeekListener?) {
        mechanics.setVirtualScrollSeekListener(listener)
    }

    override fun clearVirtualScrollSeekState() = mechanics.clearVirtualScrollSeekState()

    override fun consumeSeekRevealMetricsSuppression(
        x: Int,
        y: Int,
        now: Long,
    ): Boolean = mechanics.consumeSeekRevealMetricsSuppression(x, y, now)

    internal val interactiveScrollbarDraggingForTest: Boolean
        get() = mechanics.draggingForTest
    internal val interactiveScrollbarDisplayOffsetForTest: Int
        get() = mechanics.displayOffsetForTest()

    override fun dispatchDraw(canvas: Canvas) {
        val checkpoint = applyChildClip(
            canvas, this, cornerRadii, clipPath, clipsChildrenToBounds
        )
        super.dispatchDraw(canvas)
        restoreChildClip(canvas, checkpoint)
        mechanics.drawScrollbar(canvas)
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec)
        val (w, h) = constrainMeasured(measuredWidth, measuredHeight)
        setMeasuredDimension(w, h)
    }

    override fun onLayout(changed: Boolean, left: Int, top: Int, right: Int, bottom: Int) {
        super.onLayout(changed, left, top, right, bottom)
        mechanics.onLayoutCompleted()
    }

    override fun onScrollChanged(l: Int, t: Int, oldl: Int, oldt: Int) {
        super.onScrollChanged(l, t, oldl, oldt)
        mechanics.onScrollChanged()
    }

    override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            if (mechanics.beginInteractiveScrollbarDrag(event)) {
                super.fling(0)
                mechanics.endGesture()
                parent?.requestDisallowInterceptTouchEvent(true)
                return true
            }
            super.fling(0)
            mechanics.beginGesture()
        }
        if (mechanics.dragging) return true
        return super.onInterceptTouchEvent(event)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (mechanics.dragging) {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE ->
                    mechanics.updateInteractiveScrollbarDrag(event, final = false)
                MotionEvent.ACTION_POINTER_UP -> {
                    if (mechanics.activePointerIsGoingUp(event)) {
                        mechanics.updateInteractiveScrollbarDrag(event, final = true)
                        mechanics.finishInteractiveScrollbarDrag()
                    }
                }
                MotionEvent.ACTION_UP -> {
                    mechanics.updateInteractiveScrollbarDrag(event, final = true)
                    mechanics.finishInteractiveScrollbarDrag()
                }
                MotionEvent.ACTION_CANCEL ->
                    mechanics.finishInteractiveScrollbarDrag(resetSeek = true)
            }
            return true
        }
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                super.fling(0)
                mechanics.beginGesture()
            }
            MotionEvent.ACTION_MOVE -> mechanics.trackMove(event)
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> mechanics.endGesture()
        }
        return super.onTouchEvent(event)
    }

    override fun fling(velocityY: Int) {
        super.fling(velocityY)
        mechanics.projectFling(0, velocityY)
    }

    override fun setVirtualListInitialOffset(offset: Int) =
        mechanics.setVirtualListInitialOffset(offset)

    override fun scrollToPosition(x: Int, y: Int) = mechanics.scrollToPosition(x, y)

    override fun smoothScrollToPosition(x: Int, y: Int) =
        mechanics.smoothScrollToPosition(x, y)

    override fun onDetachedFromWindow() {
        mechanics.onDetachedFromWindow()
        super.onDetachedFromWindow()
    }
}

// ── RoundedHorizontalScrollView ───────────────────────────────────

internal class RoundedHorizontalScrollView(context: Context) :
    HorizontalScrollView(context), RoundedView, MaxConstrainedView, VyneScrollContainer {

    private val mechanics = ScrollHostMechanics(
        context,
        vertical = false,
        owner = this,
        animateScrollTo = { x, y -> smoothScrollTo(x, y) },
    )

    override var vyneMaxWidthPx: Int = 0
    override var vyneMaxHeightPx: Int = 0
    override val clipPath = Path()
    override var cornerRadii: Renderer.CornerRadii? = null
    override var clipsChildrenToBounds: Boolean = true

    override val virtualListProjection: Pair<Int, Int>
        get() = mechanics.virtualListProjection

    override var interactiveScrollbarEnabled: Boolean
        get() = mechanics.interactiveScrollbarEnabled
        set(value) {
            mechanics.interactiveScrollbarEnabled = value
        }

    override fun setVirtualScrollSeekListener(listener: VirtualScrollSeekListener?) {
        mechanics.setVirtualScrollSeekListener(listener)
    }

    override fun clearVirtualScrollSeekState() = mechanics.clearVirtualScrollSeekState()

    override fun consumeSeekRevealMetricsSuppression(
        x: Int,
        y: Int,
        now: Long,
    ): Boolean = mechanics.consumeSeekRevealMetricsSuppression(x, y, now)

    internal val interactiveScrollbarDraggingForTest: Boolean
        get() = mechanics.draggingForTest
    internal val interactiveScrollbarDisplayOffsetForTest: Int
        get() = mechanics.displayOffsetForTest()

    override fun dispatchDraw(canvas: Canvas) {
        val checkpoint = applyChildClip(
            canvas, this, cornerRadii, clipPath, clipsChildrenToBounds
        )
        super.dispatchDraw(canvas)
        restoreChildClip(canvas, checkpoint)
        mechanics.drawScrollbar(canvas)
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec)
        val (w, h) = constrainMeasured(measuredWidth, measuredHeight)
        setMeasuredDimension(w, h)
    }

    override fun onLayout(changed: Boolean, left: Int, top: Int, right: Int, bottom: Int) {
        super.onLayout(changed, left, top, right, bottom)
        mechanics.onLayoutCompleted()
    }

    override fun onScrollChanged(l: Int, t: Int, oldl: Int, oldt: Int) {
        super.onScrollChanged(l, t, oldl, oldt)
        mechanics.onScrollChanged()
    }

    override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            if (mechanics.beginInteractiveScrollbarDrag(event)) {
                super.fling(0)
                mechanics.endGesture()
                parent?.requestDisallowInterceptTouchEvent(true)
                return true
            }
            super.fling(0)
            mechanics.beginGesture()
        }
        if (mechanics.dragging) return true
        return super.onInterceptTouchEvent(event)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (mechanics.dragging) {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE ->
                    mechanics.updateInteractiveScrollbarDrag(event, final = false)
                MotionEvent.ACTION_POINTER_UP -> {
                    if (mechanics.activePointerIsGoingUp(event)) {
                        mechanics.updateInteractiveScrollbarDrag(event, final = true)
                        mechanics.finishInteractiveScrollbarDrag()
                    }
                }
                MotionEvent.ACTION_UP -> {
                    mechanics.updateInteractiveScrollbarDrag(event, final = true)
                    mechanics.finishInteractiveScrollbarDrag()
                }
                MotionEvent.ACTION_CANCEL ->
                    mechanics.finishInteractiveScrollbarDrag(resetSeek = true)
            }
            return true
        }
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                super.fling(0)
                mechanics.beginGesture()
            }
            MotionEvent.ACTION_MOVE -> mechanics.trackMove(event)
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> mechanics.endGesture()
        }
        return super.onTouchEvent(event)
    }

    override fun fling(velocityX: Int) {
        super.fling(velocityX)
        mechanics.projectFling(velocityX, 0)
    }

    override fun setVirtualListInitialOffset(offset: Int) =
        mechanics.setVirtualListInitialOffset(offset)

    override fun scrollToPosition(x: Int, y: Int) = mechanics.scrollToPosition(x, y)

    override fun smoothScrollToPosition(x: Int, y: Int) =
        mechanics.smoothScrollToPosition(x, y)

    override fun onDetachedFromWindow() {
        mechanics.onDetachedFromWindow()
        super.onDetachedFromWindow()
    }
}
