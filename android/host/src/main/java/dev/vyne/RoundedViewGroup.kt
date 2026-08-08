package dev.vyne

import android.content.Context
import android.graphics.Canvas
import android.graphics.Path
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
    FrameLayout(context), RoundedView, MaxConstrainedView {

    override var vyneMaxWidthPx: Int = 0
    override var vyneMaxHeightPx: Int = 0
    override val clipPath = Path()
    override var cornerRadii: Renderer.CornerRadii? = null
    override var clipsChildrenToBounds: Boolean = true

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

// ── RoundedScrollView ─────────────────────────────────────────────

internal class RoundedScrollView(context: Context) :
    ScrollView(context), RoundedView, MaxConstrainedView, VyneScrollContainer {

    private val projection = VirtualListProjection(context)
    private var pendingInitialOffset: Int? = null
    private var pendingScroll: PendingScroll? = null

    override var vyneMaxWidthPx: Int = 0
    override var vyneMaxHeightPx: Int = 0
    override val clipPath = Path()
    override var cornerRadii: Renderer.CornerRadii? = null
    override var clipsChildrenToBounds: Boolean = true

    override val virtualListProjection: Pair<Int, Int>
        get() = projection.offsetX to projection.offsetY

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
            if (pending.animated) super.smoothScrollTo(boundedX, boundedY)
            else super.scrollTo(boundedX, boundedY)
        }
    }

    private fun scrollBounds(): Pair<Int, Int> {
        val content = getChildAt(0)
        val viewportY =
            (height - paddingTop - paddingBottom).coerceAtLeast(0)
        val maxY = ((content?.height ?: 0) - viewportY).coerceAtLeast(0)
        return 0 to maxY
    }

    override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            super.fling(0)
            projection.beginGesture(this)
        }
        return super.onInterceptTouchEvent(event)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
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
}

// ── RoundedHorizontalScrollView ───────────────────────────────────

internal class RoundedHorizontalScrollView(context: Context) :
    HorizontalScrollView(context), RoundedView, MaxConstrainedView, VyneScrollContainer {

    private val projection = VirtualListProjection(context)
    private var pendingInitialOffset: Int? = null
    private var pendingScroll: PendingScroll? = null

    override var vyneMaxWidthPx: Int = 0
    override var vyneMaxHeightPx: Int = 0
    override val clipPath = Path()
    override var cornerRadii: Renderer.CornerRadii? = null
    override var clipsChildrenToBounds: Boolean = true

    override val virtualListProjection: Pair<Int, Int>
        get() = projection.offsetX to projection.offsetY

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
            if (pending.animated) super.smoothScrollTo(boundedX, boundedY)
            else super.scrollTo(boundedX, boundedY)
        }
    }

    private fun scrollBounds(): Pair<Int, Int> {
        val content = getChildAt(0)
        val viewportX =
            (width - paddingLeft - paddingRight).coerceAtLeast(0)
        val maxX = ((content?.width ?: 0) - viewportX).coerceAtLeast(0)
        return maxX to 0
    }

    override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            super.fling(0)
            projection.beginGesture(this)
        }
        return super.onInterceptTouchEvent(event)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
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
            if (animated) super.smoothScrollTo(x, y) else super.scrollTo(x, y)
        } else {
            // Content not laid out yet; retry after the next layout pass.
            pendingScroll = PendingScroll(x, y, animated)
            requestLayout()
        }
    }
}
