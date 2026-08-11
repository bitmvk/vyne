package dev.vyne

import android.os.SystemClock
import android.view.InputDevice
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Device-backed coverage for the native sticky view-binding path.
 *
 * Builds a real `RoundedScrollView`/`RoundedHorizontalScrollView` hosting a
 * marked `RoundedFrameLayout` with sticky cell wrappers, lays the tree out on
 * the main thread, and verifies the per-frame displacement, natural-position
 * restoration, the marker gate, marker-removal restoration, and that
 * translation-only updates never trigger a layout pass.
 *
 * The production-composition tests apply the exact generic-list wire shape
 * through the real `Renderer` (Scroll -> content Box with semantic extent
 * props -> translated cell wrappers) and prove the Android host enforces the
 * portable extent despite ScrollView's UNSPECIFIED main-axis measurement.
 */
@RunWith(AndroidJUnit4::class)
class VirtualStickyBindingInstrumentationTest {

    private val context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    private fun pointerEvent(
        downTime: Long,
        eventTime: Long,
        actionMasked: Int,
        actionIndex: Int,
        ids: IntArray,
        x: Float,
        ys: FloatArray,
    ): MotionEvent {
        val properties = Array(ids.size) { index ->
            MotionEvent.PointerProperties().apply {
                id = ids[index]
                toolType = MotionEvent.TOOL_TYPE_FINGER
            }
        }
        val coordinates = Array(ids.size) { index ->
            MotionEvent.PointerCoords().apply {
                this.x = x
                y = ys[index]
                pressure = 1f
                size = 1f
            }
        }
        val action = actionMasked or
            (actionIndex shl MotionEvent.ACTION_POINTER_INDEX_SHIFT)
        return MotionEvent.obtain(
            downTime,
            eventTime,
            action,
            ids.size,
            properties,
            coordinates,
            0,
            0,
            1f,
            1f,
            0,
            0,
            InputDevice.SOURCE_TOUCHSCREEN,
            0,
        )
    }

    private fun onMain(block: () -> Unit) {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(block)
    }

    /** One section [0,230) with a start header and an end footer. */
    private fun buildVerticalHost(): Pair<RoundedScrollView, RoundedFrameLayout> {
        val host = RoundedScrollView(context)
        val content = RoundedFrameLayout(context)
        content.isVirtualContent = true
        val header = RoundedFrameLayout(context)
        header.stickyEdge = "start"
        header.stickyBoundaryStartPx = 0f
        header.stickyBoundaryEndPx = 230f
        header.naturalTranslationY = 0f
        header.translationY = 0f
        val body = RoundedFrameLayout(context)
        val footer = RoundedFrameLayout(context)
        footer.stickyEdge = "end"
        footer.stickyBoundaryStartPx = 0f
        footer.stickyBoundaryEndPx = 230f
        footer.naturalTranslationY = 190f
        footer.translationY = 190f

        content.addView(header, FrameLayout.LayoutParams(300, 30))
        content.addView(body, FrameLayout.LayoutParams(300, 140))
        content.addView(footer, FrameLayout.LayoutParams(300, 40))
        // A tall filler gives this direct construction its scroll extent. The
        // production path below uses semantic host extent props instead.
        content.addView(
            RoundedFrameLayout(context),
            FrameLayout.LayoutParams(300, 500),
        )
        host.addView(content, FrameLayout.LayoutParams(300, 500))
        return host to content
    }

    private fun measureAndLayout(host: View) {
        host.measure(
            View.MeasureSpec.makeMeasureSpec(300, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(100, View.MeasureSpec.EXACTLY),
        )
        host.layout(0, 0, 300, 100)
    }

    @Test
    fun verticalStickyCellsDisplaceAndRestoreOnScroll() {
        onMain {
            val (host, _) = buildVerticalHost()
            measureAndLayout(host)
            val content = host.getChildAt(0) as RoundedFrameLayout
            val header = content.getChildAt(0) as RoundedFrameLayout
            val footer = content.getChildAt(2) as RoundedFrameLayout

            var layoutCount = 0
            header.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ ->
                layoutCount++
            }

            // Viewport [0,100): the header sits at its natural top; the
            // footer pins to the viewport bottom (100 - 40 = 60).
            assertEquals(0f, header.translationY, 0.5f)
            assertEquals(60f, footer.translationY, 0.5f)

            // Viewport [60,160): both displaced by the per-frame pass.
            host.scrollTo(0, 60)
            assertEquals(60f, header.translationY, 0.5f)
            assertEquals(120f, footer.translationY, 0.5f)
            // Translation-only changes must not trigger a layout pass.
            assertEquals(0, layoutCount)

            // Scroll fully past the section: both restored to natural.
            host.scrollTo(0, 300)
            assertEquals(0f, header.translationY, 0.5f)
            assertEquals(190f, footer.translationY, 0.5f)
        }
    }

    @Test
    fun unmarkedContentIsNotTraversedOnScroll() {
        onMain {
            val host = RoundedScrollView(context)
            val content = RoundedFrameLayout(context)
            // Deliberately NOT marked virtual content.
            val header = RoundedFrameLayout(context)
            header.stickyEdge = "start"
            header.stickyBoundaryStartPx = 0f
            header.stickyBoundaryEndPx = 230f
            header.naturalTranslationY = 0f
            header.translationY = 0f
            content.addView(header, FrameLayout.LayoutParams(300, 30))
            host.addView(content, FrameLayout.LayoutParams(300, 500))
            measureAndLayout(host)

            host.scrollTo(0, 60)
            // Unmarked content pays only the O(1) marker check: the sticky
            // pass never runs and the wrapper stays at its natural position.
            assertEquals(0f, header.translationY, 0.5f)
        }
    }

    @Test
    fun removingContentMarkerRestoresChildren() {
        onMain {
            val (host, _) = buildVerticalHost()
            measureAndLayout(host)
            val content = host.getChildAt(0) as RoundedFrameLayout
            val header = content.getChildAt(0) as RoundedFrameLayout
            val footer = content.getChildAt(2) as RoundedFrameLayout

            host.scrollTo(0, 60)
            assertEquals(60f, header.translationY, 0.5f)
            assertEquals(120f, footer.translationY, 0.5f)

            // The production marker-removal path: clear the marker and
            // restore every direct child before traversal is disabled.
            content.isVirtualContent = false
            content.restoreChildrenNatural()
            assertEquals(0f, header.translationY, 0.5f)
            assertEquals(190f, footer.translationY, 0.5f)
            // With the marker gone a further scroll must not re-displace.
            host.scrollTo(0, 80)
            assertEquals(0f, header.translationY, 0.5f)
        }
    }

    @Test
    fun horizontalStickyHeaderDisplacesAndRestores() {
        onMain {
            val host = RoundedHorizontalScrollView(context)
            val content = RoundedFrameLayout(context)
            content.isVirtualContent = true
            val header = RoundedFrameLayout(context)
            header.stickyEdge = "start"
            header.stickyBoundaryStartPx = 0f
            header.stickyBoundaryEndPx = 230f
            header.naturalTranslationX = 0f
            header.translationX = 0f
            content.addView(header, FrameLayout.LayoutParams(30, 100))
            // Wide filler gives the horizontal content its scroll extent.
            content.addView(
                RoundedFrameLayout(context),
                FrameLayout.LayoutParams(500, 100),
            )
            host.addView(content, FrameLayout.LayoutParams(500, 100))
            host.measure(
                View.MeasureSpec.makeMeasureSpec(100, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(100, View.MeasureSpec.EXACTLY),
            )
            host.layout(0, 0, 100, 100)

            host.scrollTo(60, 0)
            assertEquals(60f, header.translationX, 0.5f)
            host.scrollTo(300, 0)
            assertEquals(0f, header.translationX, 0.5f)
        }
    }

    // ── Production composition through the real Renderer ───────────────
    // The generic-list wire shape is: Scroll -> content Box with semantic
    // extent props -> translated cell wrappers. Android enforces the extent
    // during measurement; no platform workaround leaks into the child tree.

    @Test
    fun verticalProductionContentReachesDeclaredExtentAndScrolls() {
        val renderer = Renderer(context, {})
        try {
            val extentDp = 10_000
            val ops = mutableListOf<RenderOperation>()
            ops += RenderOperation.Create(1, "Scroll")
            ops += RenderOperation.SetProps(1, mapOf("width" to 300, "height" to 100))
            ops += RenderOperation.Create(2, "Box")
            ops += RenderOperation.SetProps(
                2,
                mapOf(
                    "width" to 300,
                    "height" to extentDp,
                    "_virtual_content_width" to 300,
                    "_virtual_content_height" to extentDp,
                ),
            )
            // One realized cell wrapper; no fake extent child.
            ops += RenderOperation.Create(4, "Box")
            ops += RenderOperation.SetProps(
                4,
                mapOf("width" to 300, "height" to 10, "translation_y" to 0f),
            )
            ops += RenderOperation.InsertChild(2, 4, 0)
            ops += RenderOperation.InsertChild(1, 2, 0)
            ops += RenderOperation.InsertChild(0, 1, 0)
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(RenderTransaction(1, ops)),
            )
            val density = renderer.root.resources.displayMetrics.density
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((300 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)
            val scroll = renderer.root.getChildAt(0) as RoundedScrollView
            val content = scroll.getChildAt(0)
            // The host-enforced semantic prop gives the declared extent.
            assertTrue(
                "content collapsed to ${content.height / density}dp",
                content.height / density >= extentDp - 1f,
            )
            // Real scroll range and programmatic scrolling.
            assertTrue(content.height - scroll.height > 0)
            scroll.scrollTo(0, (500 * density).toInt())
            assertEquals(500f, scroll.scrollY / density, 1.0f)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun horizontalProductionContentReachesDeclaredExtentAndScrolls() {
        val renderer = Renderer(context, {})
        try {
            val extentDp = 10_000
            val ops = mutableListOf<RenderOperation>()
            ops += RenderOperation.Create(1, "HorizontalScroll")
            ops += RenderOperation.SetProps(1, mapOf("width" to 100, "height" to 100))
            ops += RenderOperation.Create(2, "Box")
            ops += RenderOperation.SetProps(
                2,
                mapOf(
                    "width" to extentDp,
                    "height" to 100,
                    "_virtual_content_width" to extentDp,
                    "_virtual_content_height" to 100,
                ),
            )
            ops += RenderOperation.Create(4, "Box")
            ops += RenderOperation.SetProps(
                4,
                mapOf("width" to 10, "height" to 100, "translation_x" to 0f),
            )
            ops += RenderOperation.InsertChild(2, 4, 0)
            ops += RenderOperation.InsertChild(1, 2, 0)
            ops += RenderOperation.InsertChild(0, 1, 0)
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(RenderTransaction(1, ops)),
            )
            val density = renderer.root.resources.displayMetrics.density
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)
            val scroll = renderer.root.getChildAt(0) as RoundedHorizontalScrollView
            val content = scroll.getChildAt(0)
            assertTrue(
                "content collapsed to ${content.width / density}dp",
                content.width / density >= extentDp - 1f,
            )
            assertTrue(content.width - scroll.width > 0)
            scroll.scrollTo((500 * density).toInt(), 0)
            assertEquals(500f, scroll.scrollX / density, 1.0f)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun verticalStickyDisplacementThroughProductionComposition() {
        val renderer = Renderer(context, {})
        try {
            val extentDp = 500
            val ops = mutableListOf<RenderOperation>()
            ops += RenderOperation.Create(1, "Scroll")
            ops += RenderOperation.SetProps(1, mapOf("width" to 300, "height" to 100))
            ops += RenderOperation.Create(2, "Box")
            ops += RenderOperation.SetProps(
                2,
                mapOf(
                    "width" to 300,
                    "height" to extentDp,
                    "_virtual_content" to true,
                    "_virtual_content_width" to 300,
                    "_virtual_content_height" to extentDp,
                ),
            )
            // Sticky header (natural 0, section [0,230)).
            ops += RenderOperation.Create(4, "Box")
            ops += RenderOperation.SetProps(
                4,
                mapOf(
                    "width" to 300,
                    "height" to 30,
                    "translation_y" to 0f,
                    "_virtual_sticky_edge" to "start",
                    "_virtual_sticky_boundary_start" to 0,
                    "_virtual_sticky_boundary_end" to 230,
                ),
            )
            ops += RenderOperation.InsertChild(2, 4, 0)
            // Sticky footer (natural 190).
            ops += RenderOperation.Create(5, "Box")
            ops += RenderOperation.SetProps(
                5,
                mapOf(
                    "width" to 300,
                    "height" to 40,
                    "translation_y" to 190f,
                    "_virtual_sticky_edge" to "end",
                    "_virtual_sticky_boundary_start" to 0,
                    "_virtual_sticky_boundary_end" to 230,
                ),
            )
            ops += RenderOperation.InsertChild(2, 5, 1)
            ops += RenderOperation.InsertChild(1, 2, 0)
            ops += RenderOperation.InsertChild(0, 1, 0)
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(RenderTransaction(1, ops)),
            )
            val density = renderer.root.resources.displayMetrics.density
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((300 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)
            val scroll = renderer.root.getChildAt(0) as RoundedScrollView
            val content = scroll.getChildAt(0) as ViewGroup
            val header = content.getChildAt(0) as RoundedFrameLayout
            val footer = content.getChildAt(1) as RoundedFrameLayout
            // The semantic extent makes the sticky host scrollable.
            assertTrue(content.height / density >= extentDp - 1f)
            // Viewport [60,160): both displaced.
            scroll.scrollTo(0, (60 * density).toInt())
            assertEquals(60f, header.translationY / density, 1.0f)
            assertEquals(120f, footer.translationY / density, 1.0f)
            // Past the section: both restored.
            scroll.scrollTo(0, (300 * density).toInt())
            assertEquals(0f, header.translationY / density, 1.0f)
            assertEquals(190f, footer.translationY / density, 1.0f)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun transactionalScrollbarSeekWaitsForAcceptedRevealAndDoesNotWedge() {
        val events = mutableListOf<NativeEvent>()
        val renderer = Renderer(context, { events.add(it) })
        try {
            val extentDp = 10_000
            val ops = mutableListOf<RenderOperation>()
            ops += RenderOperation.Create(1, "Scroll")
            ops += RenderOperation.SetProps(
                1,
                mapOf(
                    "width" to 300,
                    "height" to 100,
                    "interactive_scrollbar" to true,
                ),
            )
            ops += RenderOperation.Create(2, "Box")
            ops += RenderOperation.SetProps(
                2,
                mapOf(
                    "width" to 300,
                    "height" to extentDp,
                    "_virtual_content_width" to 300,
                    "_virtual_content_height" to extentDp,
                ),
            )
            ops += RenderOperation.InsertChild(1, 2, 0)
            ops += RenderOperation.Listen(1, "scroll_metrics", 10, "latest")
            ops += RenderOperation.Listen(1, "scroll_seek", 11, "latest")
            ops += RenderOperation.InsertChild(0, 1, 0)
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(RenderTransaction(1, ops)),
            )
            val density = renderer.root.resources.displayMetrics.density
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((300 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)
            val scroll = renderer.root.getChildAt(0) as RoundedScrollView
            val now = SystemClock.uptimeMillis()
            val x = scroll.width - 1f

            fun drag(base: Long): Float {
                val down = MotionEvent.obtain(base, base, MotionEvent.ACTION_DOWN, x, 20f, 0)
                val move = MotionEvent.obtain(
                    base,
                    base + 40,
                    MotionEvent.ACTION_MOVE,
                    x,
                    scroll.height - 5f,
                    0,
                )
                val up = MotionEvent.obtain(
                    base,
                    base + 41,
                    MotionEvent.ACTION_UP,
                    x,
                    scroll.height - 5f,
                    0,
                )
                try {
                    assertTrue(scroll.dispatchTouchEvent(down))
                    assertTrue(scroll.dispatchTouchEvent(move))
                    assertEquals(0, scroll.scrollY)
                    assertTrue(scroll.interactiveScrollbarDisplayOffsetForTest > 0)
                    assertTrue(scroll.dispatchTouchEvent(up))
                } finally {
                    down.recycle()
                    move.recycle()
                    up.recycle()
                }
                val seek = events.last { it.name == "scroll_seek" }
                assertTrue(seek.payload["final"] == true)
                return (seek.payload.getValue("target_offset_y") as Number).toFloat()
            }

            val rejectedTarget = drag(now)
            val rejected = renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(
                        RenderOperation.ScrollTo(1, 0f, rejectedTarget, false),
                        RenderOperation.SetProps(999, mapOf("width" to 1)),
                    ),
                ),
            )
            assertEquals(Renderer.ApplyResult.REJECTED_KNOWN, rejected)
            assertEquals(0, scroll.scrollY)

            // A fresh final seek survives a candidate which temporarily
            // removes its listener and disables the scrollbar, then fails
            // after those mutations. Existing transaction rollback restores
            // the feature without changing commit architecture.
            events.clear()
            val acceptedTarget = drag(now + 100)
            val rolledBack = renderer.applyDirectTransaction(
                RenderTransaction(
                    3,
                    listOf(
                        RenderOperation.Unlisten(1, "scroll_seek"),
                        RenderOperation.SetProps(
                            1,
                            mapOf("interactive_scrollbar" to false),
                        ),
                        RenderOperation.Create(99, "Box"),
                        // Scroll already owns content id=2: the second child
                        // fails at apply time after the candidate mutations.
                        RenderOperation.InsertChild(1, 99, 1),
                    ),
                ),
            )
            assertEquals(Renderer.ApplyResult.PARTIAL, rolledBack)
            assertTrue(scroll.interactiveScrollbarEnabled)
            assertTrue(scroll.interactiveScrollbarDisplayOffsetForTest > 0)

            events.clear()
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        4,
                        listOf(
                            RenderOperation.SetProps(1, mapOf("width" to 299)),
                            RenderOperation.ScrollTo(1, 0f, acceptedTarget, false),
                        ),
                    ),
                ),
            )
            // Force the follow-up layout observation inside the suppression
            // deadline. Both scroll and layout echoes must stay native.
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((300 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)
            assertTrue(scroll.scrollY / density > 8_000f)
            assertTrue(events.none { it.name == "scroll_metrics" })
            assertEquals(scroll.scrollY, scroll.interactiveScrollbarDisplayOffsetForTest)

            // Losing the active pointer resets both native drag ownership and
            // the provisional transactional thumb/watchdog state.
            val missingX = scroll.width - 1f
            val missingDown = pointerEvent(
                now + 200,
                now + 200,
                MotionEvent.ACTION_DOWN,
                0,
                intArrayOf(21),
                missingX,
                floatArrayOf(20f),
            )
            val missingMove = pointerEvent(
                now + 200,
                now + 216,
                MotionEvent.ACTION_MOVE,
                0,
                intArrayOf(22),
                missingX,
                floatArrayOf(scroll.height - 5f),
            )
            try {
                assertTrue(scroll.dispatchTouchEvent(missingDown))
                assertTrue(scroll.interactiveScrollbarDraggingForTest)
                assertTrue(scroll.dispatchTouchEvent(missingMove))
                assertTrue(!scroll.interactiveScrollbarDraggingForTest)
                assertEquals(scroll.scrollY, scroll.interactiveScrollbarDisplayOffsetForTest)
            } finally {
                missingDown.recycle()
                missingMove.recycle()
            }
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun interactiveScrollbarDragsAcrossFullSemanticExtent() {
        val renderer = Renderer(context, {})
        try {
            val extentDp = 10_000
            val ops = mutableListOf<RenderOperation>()
            ops += RenderOperation.Create(1, "Scroll")
            ops += RenderOperation.SetProps(
                1,
                mapOf(
                    "width" to 300,
                    "height" to 100,
                    "interactive_scrollbar" to true,
                ),
            )
            ops += RenderOperation.Create(2, "Box")
            ops += RenderOperation.SetProps(
                2,
                mapOf(
                    "width" to 300,
                    "height" to extentDp,
                    "_virtual_content_width" to 300,
                    "_virtual_content_height" to extentDp,
                ),
            )
            ops += RenderOperation.Create(3, "Box")
            ops += RenderOperation.SetProps(3, mapOf("width" to 300, "height" to 10))
            ops += RenderOperation.InsertChild(2, 3, 0)
            ops += RenderOperation.InsertChild(1, 2, 0)
            ops += RenderOperation.InsertChild(0, 1, 0)
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(RenderTransaction(1, ops)),
            )
            val density = renderer.root.resources.displayMetrics.density
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((300 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)
            val scroll = renderer.root.getChildAt(0) as RoundedScrollView
            assertTrue(scroll.interactiveScrollbarEnabled)
            assertTrue(!scroll.isVerticalScrollBarEnabled)

            val now = SystemClock.uptimeMillis()
            val x = scroll.width - 1f
            val down = MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, x, 20f, 0)
            val move = MotionEvent.obtain(now, now + 16, MotionEvent.ACTION_MOVE, x, scroll.height - 5f, 0)
            val up = MotionEvent.obtain(now, now + 32, MotionEvent.ACTION_UP, x, scroll.height - 5f, 0)
            try {
                assertTrue(scroll.dispatchTouchEvent(down))
                assertTrue(scroll.dispatchTouchEvent(move))
                assertTrue(scroll.dispatchTouchEvent(up))
            } finally {
                down.recycle()
                move.recycle()
                up.recycle()
            }
            assertTrue(
                "far drag only reached ${scroll.scrollY / density}dp",
                scroll.scrollY / density > 8_000f,
            )
            assertEquals(scroll.scrollY, scroll.virtualListProjection.second)

            // The pointer which starts the drag keeps ownership even if a
            // second pointer arrives and MotionEvent pointer ordering changes.
            scroll.scrollTo(0, 0)
            val multiStart = now + 100
            val ownerDown = pointerEvent(
                multiStart,
                multiStart,
                MotionEvent.ACTION_DOWN,
                0,
                intArrayOf(7),
                x,
                floatArrayOf(20f),
            )
            val secondDown = pointerEvent(
                multiStart,
                multiStart + 8,
                MotionEvent.ACTION_POINTER_DOWN,
                1,
                intArrayOf(7, 9),
                x,
                floatArrayOf(20f, scroll.height - 5f),
            )
            val reorderedMove = pointerEvent(
                multiStart,
                multiStart + 16,
                MotionEvent.ACTION_MOVE,
                0,
                intArrayOf(9, 7),
                x,
                floatArrayOf(scroll.height - 5f, 30f),
            )
            val ownerUp = pointerEvent(
                multiStart,
                multiStart + 24,
                MotionEvent.ACTION_POINTER_UP,
                1,
                intArrayOf(9, 7),
                x,
                floatArrayOf(scroll.height - 5f, 30f),
            )
            val remainingUp = pointerEvent(
                multiStart,
                multiStart + 32,
                MotionEvent.ACTION_UP,
                0,
                intArrayOf(9),
                x,
                floatArrayOf(scroll.height - 5f),
            )
            try {
                assertTrue(scroll.dispatchTouchEvent(ownerDown))
                assertTrue(scroll.interactiveScrollbarDraggingForTest)
                assertTrue(scroll.dispatchTouchEvent(secondDown))
                assertTrue(scroll.dispatchTouchEvent(reorderedMove))
                val maximum = (scroll.getChildAt(0).height - scroll.height).coerceAtLeast(1)
                assertTrue("second pointer stole scrollbar", scroll.scrollY < maximum / 2)
                assertTrue(scroll.dispatchTouchEvent(ownerUp))
                assertTrue(!scroll.interactiveScrollbarDraggingForTest)
                scroll.dispatchTouchEvent(remainingUp)
            } finally {
                ownerDown.recycle()
                secondDown.recycle()
                reorderedMove.recycle()
                ownerUp.recycle()
                remainingUp.recycle()
            }

            // A malformed stream which loses the active pointer terminates
            // cleanly rather than transferring ownership to a remaining one.
            val missingDown = pointerEvent(
                multiStart + 40,
                multiStart + 40,
                MotionEvent.ACTION_DOWN,
                0,
                intArrayOf(11),
                x,
                floatArrayOf(20f),
            )
            val missingMove = pointerEvent(
                multiStart + 40,
                multiStart + 48,
                MotionEvent.ACTION_MOVE,
                0,
                intArrayOf(12),
                x,
                floatArrayOf(scroll.height - 5f),
            )
            try {
                assertTrue(scroll.dispatchTouchEvent(missingDown))
                assertTrue(scroll.interactiveScrollbarDraggingForTest)
                assertTrue(scroll.dispatchTouchEvent(missingMove))
                assertTrue(!scroll.interactiveScrollbarDraggingForTest)
            } finally {
                missingDown.recycle()
                missingMove.recycle()
            }

            // Disabling/removing the prop during a drag releases ownership.
            val disableDown = MotionEvent.obtain(
                multiStart + 64,
                multiStart + 64,
                MotionEvent.ACTION_DOWN,
                x,
                20f,
                0,
            )
            try {
                assertTrue(scroll.dispatchTouchEvent(disableDown))
                assertTrue(scroll.interactiveScrollbarDraggingForTest)
            } finally {
                disableDown.recycle()
            }
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        2,
                        listOf(RenderOperation.RemoveProp(1, "interactive_scrollbar")),
                    ),
                ),
            )
            assertTrue(!scroll.interactiveScrollbarEnabled)
            assertTrue(!scroll.interactiveScrollbarDraggingForTest)
            assertTrue(scroll.isVerticalScrollBarEnabled)
        } finally {
            renderer.dispose()
        }
    }
}
