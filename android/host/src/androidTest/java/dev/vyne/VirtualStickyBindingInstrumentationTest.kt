package dev.vyne

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
 * through the real `Renderer` (Scroll -> content Box with an inert extent
 * sentinel first child -> translated cell wrappers) and prove the sentinel
 * gives the host a real scroll range (the device blocker that FrameLayout's
 * collapse under ScrollView's UNSPECIFIED measurement would otherwise
 * cause).
 */
@RunWith(AndroidJUnit4::class)
class VirtualStickyBindingInstrumentationTest {

    private val context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

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
        // A tall filler gives the content its scroll extent.  (FrameLayout
        // collapses to its children under ScrollView's UNSPECIFIED
        // measurement; the production generic composition now uses an inert
        // extent sentinel first child for the same purpose — see the
        // production-composition tests below.)
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
    // The generic-list wire shape is: Scroll -> content Box -> [inert
    // extent sentinel (first child), translated cell wrappers].  The
    // sentinel is what gives the host a real scroll range; without it the
    // FrameLayout content collapses to its tallest realized cell under
    // ScrollView's UNSPECIFIED main-axis measurement.

    @Test
    fun verticalProductionContentReachesDeclaredExtentAndScrolls() {
        val renderer = Renderer(context, {})
        try {
            val extentDp = 10_000
            val ops = mutableListOf<RenderOperation>()
            ops += RenderOperation.Create(1, "Scroll")
            ops += RenderOperation.SetProps(1, mapOf("width" to 300, "height" to 100))
            ops += RenderOperation.Create(2, "Box")
            ops += RenderOperation.SetProps(2, mapOf("width" to 300, "height" to extentDp))
            // Inert extent sentinel, first child, full declared extent.
            ops += RenderOperation.Create(3, "Box")
            ops += RenderOperation.SetProps(3, mapOf("width" to 300, "height" to extentDp))
            ops += RenderOperation.InsertChild(2, 3, 0)
            // One realized cell wrapper.
            ops += RenderOperation.Create(4, "Box")
            ops += RenderOperation.SetProps(
                4,
                mapOf("width" to 300, "height" to 10, "translation_y" to 0f),
            )
            ops += RenderOperation.InsertChild(2, 4, 1)
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
            // The sentinel gives the content its declared extent.
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
            ops += RenderOperation.SetProps(2, mapOf("width" to extentDp, "height" to 100))
            // Inert extent sentinel, first child, full declared extent.
            ops += RenderOperation.Create(3, "Box")
            ops += RenderOperation.SetProps(3, mapOf("width" to extentDp, "height" to 100))
            ops += RenderOperation.InsertChild(2, 3, 0)
            ops += RenderOperation.Create(4, "Box")
            ops += RenderOperation.SetProps(
                4,
                mapOf("width" to 10, "height" to 100, "translation_x" to 0f),
            )
            ops += RenderOperation.InsertChild(2, 4, 1)
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
                ),
            )
            // Inert extent sentinel (first child) sized to the full extent.
            ops += RenderOperation.Create(3, "Box")
            ops += RenderOperation.SetProps(3, mapOf("width" to 300, "height" to extentDp))
            ops += RenderOperation.InsertChild(2, 3, 0)
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
            ops += RenderOperation.InsertChild(2, 4, 1)
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
            ops += RenderOperation.InsertChild(2, 5, 2)
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
            val header = content.getChildAt(1) as RoundedFrameLayout
            val footer = content.getChildAt(2) as RoundedFrameLayout
            // The sentinel gives the content its extent (sticky requires a
            // scrollable host).
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
}
