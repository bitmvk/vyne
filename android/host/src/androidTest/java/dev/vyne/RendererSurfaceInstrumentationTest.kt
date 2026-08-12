package dev.vyne

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.RectF
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlin.math.abs
import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Device-backed coverage for the native surface not exercised by JVM tests. */
@RunWith(AndroidJUnit4::class)
class RendererSurfaceInstrumentationTest {
    private val context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun everyPrimitiveKindCreatesItsExpectedNativeView() {
        val expected =
            mapOf(
                "Box" to ViewGroup::class.java,
                "Layout" to LinearLayout::class.java,
                "Scroll" to ScrollView::class.java,
                "HorizontalScroll" to HorizontalScrollView::class.java,
                "Text" to TextView::class.java,
                "TextInput" to EditText::class.java,
                "Image" to ImageView::class.java,
                "Path" to PathView::class.java,
                "Canvas" to CanvasView::class.java,
            )
        for ((kind, nativeClass) in expected) {
            withMounted(kind) { view, _ ->
                assertTrue(
                    "$kind created ${view.javaClass.name}",
                    nativeClass.isInstance(view),
                )
            }
        }
    }

    @Test
    fun widthHeightAndMinimumsUseDensityAwarePixels() {
        withMounted(
            "Box",
            mapOf(
                "width" to 80,
                "height" to 30,
                "min_width" to 20,
                "min_height" to 10,
            ),
        ) { view, _ ->
            val density = view.resources.displayMetrics.density
            assertEquals((80 * density).toInt(), view.layoutParams.width)
            assertEquals((30 * density).toInt(), view.layoutParams.height)
            assertEquals((20 * density).toInt(), view.minimumWidth)
            assertEquals((10 * density).toInt(), view.minimumHeight)
        }
    }

    @Test
    fun marginsAreStoredOnNativeLayoutParams() {
        withMounted(
            "Box",
            mapOf(
                "margin_start" to 3,
                "margin_top" to 4,
                "margin_end" to 5,
                "margin_bottom" to 6,
            ),
        ) { view, _ ->
            val density = view.resources.displayMetrics.density
            val params = view.layoutParams as ViewGroup.MarginLayoutParams
            assertEquals((3 * density).toInt(), params.marginStart)
            assertEquals((4 * density).toInt(), params.topMargin)
            assertEquals((5 * density).toInt(), params.marginEnd)
            assertEquals((6 * density).toInt(), params.bottomMargin)
        }
    }

    @Test
    fun presentationTransformsAndOpacityApplyAndReset() {
        withMounted(
            "Box",
            mapOf(
                "opacity" to 0.4,
                "translation_x" to 7,
                "translation_y" to 8,
                "rotation" to 15,
                "rotation_x" to 5,
                "rotation_y" to 6,
                "scale_x" to 1.2,
                "scale_y" to 0.8,
            ),
        ) { view, renderer ->
            val density = view.resources.displayMetrics.density
            assertTrue(abs(view.alpha - 0.4f) < 0.001f)
            assertTrue(abs(view.translationX - 7 * density) < 1f)
            assertTrue(abs(view.translationY - 8 * density) < 1f)
            assertEquals(15f, view.rotation)
            assertEquals(5f, view.rotationX)
            assertEquals(6f, view.rotationY)
            assertEquals(1.2f, view.scaleX)
            assertEquals(0.8f, view.scaleY)

            renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(
                        RenderOperation.RemoveProp(1, "opacity"),
                        RenderOperation.RemoveProp(1, "translation_x"),
                        RenderOperation.RemoveProp(1, "translation_y"),
                        RenderOperation.RemoveProp(1, "rotation"),
                        RenderOperation.RemoveProp(1, "rotation_x"),
                        RenderOperation.RemoveProp(1, "rotation_y"),
                        RenderOperation.RemoveProp(1, "scale_x"),
                        RenderOperation.RemoveProp(1, "scale_y"),
                    ),
                )
            )
            assertEquals(1f, view.alpha)
            assertEquals(0f, view.translationX)
            assertEquals(0f, view.translationY)
            assertEquals(0f, view.rotation)
            assertEquals(1f, view.scaleX)
            assertEquals(1f, view.scaleY)
        }
    }

    @Test
    fun visibilityEnabledFocusableAndClickableApply() {
        withMounted(
            "Box",
            mapOf(
                "visible" to false,
                "enabled" to false,
                "focusable" to true,
                "clickable" to true,
            ),
        ) { view, _ ->
            assertEquals(View.GONE, view.visibility)
            assertFalse(view.isEnabled)
            assertTrue(view.isFocusable)
            assertTrue(view.isClickable)
        }
    }

    @Test
    fun textTypographyPropertiesApplyAndRemove() {
        withMounted(
            "Text",
            mapOf(
                "text" to "styled",
                "font_size" to 22,
                "line_height" to 28,
                "include_font_padding" to false,
                "text_color" to "#FF00FF",
            ),
        ) { raw, renderer ->
            val view = raw as TextView
            assertEquals("styled", view.text.toString())
            val expectedTextSize =
                TypedValue.applyDimension(
                    TypedValue.COMPLEX_UNIT_SP,
                    22f,
                    view.resources.displayMetrics,
                )
            assertTrue(abs(view.textSize - expectedTextSize) < 0.5f)
            assertFalse(view.includeFontPadding)
            assertEquals(0xFFFF00FF.toInt(), view.currentTextColor)

            renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(
                        RenderOperation.RemoveProp(1, "text"),
                        RenderOperation.RemoveProp(1, "include_font_padding"),
                    ),
                )
            )
            assertEquals("", view.text.toString())
            assertTrue(view.includeFontPadding)
        }
    }

    @Test
    fun textInputPropsAndProgrammaticEchoSuppressionWork() {
        val events = mutableListOf<NativeEvent>()
        val renderer = Renderer(context, events::add)
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1,
                    listOf(
                        RenderOperation.Create(1, "TextInput"),
                        RenderOperation.SetProps(
                            1,
                            mapOf("text" to "initial", "hint" to "hint"),
                        ),
                        RenderOperation.Listen(1, "text_change", 9, "all"),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                )
            )
            val input = renderer.root.getChildAt(0) as EditText
            assertEquals("initial", input.text.toString())
            assertEquals("hint", input.hint.toString())
            assertTrue(events.isEmpty())

            input.setText("native")
            assertEquals(1, events.size)
            assertEquals("native", events.single().payload["text"])
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun focusListenerEmitsBothTransitions() {
        val events = mutableListOf<NativeEvent>()
        val renderer = Renderer(context, events::add)
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1,
                    listOf(
                        RenderOperation.Create(1, "TextInput"),
                        RenderOperation.Listen(1, "focus_change", 7, "all"),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                )
            )
            val input = renderer.root.getChildAt(0) as EditText
            input.onFocusChangeListener?.onFocusChange(input, true)
            input.onFocusChangeListener?.onFocusChange(input, false)
            assertEquals(listOf(true, false), events.map { it.payload["has_focus"] })
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun controlledFocusUsesInputControllerForBothStates() {
        val renderer = Renderer(context, {})
        try {
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        1,
                        listOf(
                            RenderOperation.Create(1, "TextInput"),
                            RenderOperation.InsertChild(0, 1, 0),
                            RenderOperation.SetProp(1, "focused", true),
                        ),
                    ),
                ),
            )
            val input = renderer.root.getChildAt(0) as EditText
            assertTrue(input.hasFocus())
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        2,
                        listOf(RenderOperation.SetProp(1, "focused", false)),
                    ),
                ),
            )
            assertFalse(input.hasFocus())
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun imageScaleTypesApplyAndReset() {
        withMounted(
            "Image",
            mapOf("scale_type" to "center_crop", "source" to "missing"),
        ) { raw, renderer ->
            val image = raw as ImageView
            assertEquals(ImageView.ScaleType.CENTER_CROP, image.scaleType)
            assertEquals(null, image.drawable)
            renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(RenderOperation.RemoveProp(1, "scale_type")),
                )
            )
            assertEquals(ImageView.ScaleType.FIT_CENTER, image.scaleType)
        }
    }

    @Test
    fun layoutOrientationChangesAndResets() {
        withMounted(
            "Layout",
            mapOf("orientation" to "horizontal"),
        ) { raw, renderer ->
            val layout = raw as LinearLayout
            assertEquals(LinearLayout.HORIZONTAL, layout.orientation)
            renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(RenderOperation.RemoveProp(1, "orientation")),
                )
            )
            assertEquals(LinearLayout.VERTICAL, layout.orientation)
        }
    }

    @Test
    fun sharedAlignmentApplicatorsUpdateAndResetLayoutGravity() {
        withMounted(
            "Layout",
            mapOf(
                "align_items" to "end",
                "justify_content" to "center",
            ),
        ) { raw, renderer ->
            val layout = raw as LinearLayout
            assertEquals(Gravity.END, layout.gravity and Gravity.RELATIVE_HORIZONTAL_GRAVITY_MASK)
            assertEquals(Gravity.CENTER_VERTICAL, layout.gravity and Gravity.VERTICAL_GRAVITY_MASK)

            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        2,
                        listOf(
                            RenderOperation.RemoveProp(1, "align_items"),
                            RenderOperation.RemoveProp(1, "justify_content"),
                        ),
                    ),
                ),
            )
            assertEquals(Gravity.START, layout.gravity and Gravity.RELATIVE_HORIZONTAL_GRAVITY_MASK)
            assertEquals(Gravity.TOP, layout.gravity and Gravity.VERTICAL_GRAVITY_MASK)
        }
    }

    @Test
    fun scrollAcceptsOneChildAndRejectsASecondAtomically() {
        val renderer = Renderer(context, {})
        try {
            val first =
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        1,
                        listOf(
                            RenderOperation.Create(1, "Scroll"),
                            RenderOperation.Create(2, "Text"),
                            RenderOperation.InsertChild(1, 2, 0),
                            RenderOperation.InsertChild(0, 1, 0),
                        ),
                    )
                )
            assertEquals(Renderer.ApplyResult.OK, first)
            val scroll = renderer.root.getChildAt(0) as ScrollView

            val second =
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        2,
                        listOf(
                            RenderOperation.Create(3, "Text"),
                            RenderOperation.InsertChild(1, 3, 1),
                        ),
                    )
                )
            assertEquals(Renderer.ApplyResult.PARTIAL, second)
            assertEquals(1, scroll.childCount)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun canvasDrawListProducesPixels() {
        val draw =
            JSONArray(
                """[
                    {"kind":"rect","x":0,"y":0,"width":20,"height":20,
                     "fill":"#FF0000FF"}
                ]"""
            )
        withMounted(
            "Canvas",
            mapOf(
                "width" to 20,
                "height" to 20,
                "view_box" to JSONArray("[0,0,20,20]"),
                "draw" to draw,
            ),
        ) { view, _ ->
            val size = (20 * view.resources.displayMetrics.density).toInt()
            view.measure(
                View.MeasureSpec.makeMeasureSpec(size, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(size, View.MeasureSpec.EXACTLY),
            )
            view.layout(0, 0, size, size)
            val bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap))
            assertTrue(bitmap.getPixel(size / 2, size / 2) != 0)
        }
    }

    @Test
    fun accessibilityStateReachesNativeNodeInfo() {
        withMounted(
            "Box",
            mapOf(
                "content_description" to "control",
                "accessibility_role" to "checkbox",
                "accessibility_checked" to true,
                "accessibility_selected" to true,
                "accessibility_state_description" to "selected",
            ),
        ) { view, _ ->
            val info = view.createAccessibilityNodeInfo()
            assertEquals("control", view.contentDescription.toString())
            assertTrue(info.isCheckable)
            assertTrue(info.isChecked)
            assertTrue(info.isSelected)
        }
    }

    @Test
    fun unlistenDetachesClickCallback() {
        val events = mutableListOf<NativeEvent>()
        val renderer = Renderer(context, events::add)
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1,
                    listOf(
                        RenderOperation.Create(1, "Box"),
                        RenderOperation.Listen(1, "click", 4, "all"),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                )
            )
            val box = renderer.root.getChildAt(0)
            box.performClick()
            renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(RenderOperation.Unlisten(1, "click")),
                )
            )
            box.performClick()
            assertEquals(1, events.size)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun removePropRestoresPaddingAndMargins() {
        withMounted(
            "Box",
            mapOf("padding_start" to 9, "margin_start" to 11),
        ) { view, renderer ->
            assertTrue(view.paddingLeft > 0)
            assertTrue(
                (view.layoutParams as ViewGroup.MarginLayoutParams).marginStart > 0
            )
            renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(
                        RenderOperation.RemoveProp(1, "padding_start"),
                        RenderOperation.RemoveProp(1, "margin_start"),
                    ),
                )
            )
            assertEquals(0, view.paddingLeft)
            assertEquals(
                0,
                (view.layoutParams as ViewGroup.MarginLayoutParams).marginStart,
            )
        }
    }

    @Test
    fun layoutMetricsReportLogicalBounds() {
        val events = mutableListOf<NativeEvent>()
        val renderer = Renderer(context, events::add)
        try {
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        1,
                        listOf(
                            RenderOperation.Create(1, "Box"),
                            RenderOperation.SetProps(
                                1,
                                mapOf("width" to 80, "height" to 40),
                            ),
                            RenderOperation.Listen(1, "layout_metrics", 9, "latest"),
                            RenderOperation.InsertChild(0, 1, 0),
                        ),
                    ),
                ),
            )
            val density = renderer.root.resources.displayMetrics.density
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((200 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((200 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)

            val event = events.last { it.name == "layout_metrics" }
            assertEquals(1, event.target)
            assertEquals(9, event.handler)
            assertEquals("latest", event.delivery)
            assertEquals(80f, (event.payload.getValue("width") as Number).toFloat(), 0.01f)
            assertEquals(40f, (event.payload.getValue("height") as Number).toFloat(), 0.01f)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun scrollMetricsReportViewportContentAndOffset() {
        val events = mutableListOf<NativeEvent>()
        val renderer = Renderer(context, events::add)
        try {
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        1,
                        listOf(
                            RenderOperation.Create(1, "Scroll"),
                            RenderOperation.SetProps(
                                1,
                                mapOf("width" to 200, "height" to 100),
                            ),
                            RenderOperation.Create(2, "Box"),
                            RenderOperation.SetProps(
                                2,
                                mapOf("width" to 200, "height" to 500),
                            ),
                            RenderOperation.InsertChild(1, 2, 0),
                            RenderOperation.Listen(1, "scroll_metrics", 10, "latest"),
                            RenderOperation.InsertChild(0, 1, 0),
                        ),
                    ),
                ),
            )
            val density = renderer.root.resources.displayMetrics.density
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((200 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)
            val scroll = renderer.root.getChildAt(0) as ScrollView
            val content = scroll.getChildAt(0)
            content.layout(
                0,
                0,
                (200 * density).toInt(),
                (500 * density).toInt(),
            )
            scroll.scrollTo(0, (60 * density).toInt())

            val event = events.last { it.name == "scroll_metrics" }
            assertEquals(1, event.target)
            assertEquals(10, event.handler)
            assertEquals("latest", event.delivery)
            assertEquals(60f, (event.payload.getValue("offset_y") as Number).toFloat(), 0.51f)
            assertEquals(100f, (event.payload.getValue("viewport_height") as Number).toFloat(), 0.51f)
            assertEquals(500f, (event.payload.getValue("content_height") as Number).toFloat(), 0.51f)
            assertTrue((event.payload.getValue("event_time") as Number).toLong() >= 0L)

            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        2,
                        listOf(RenderOperation.ScrollTo(1, 0f, 80f, false)),
                    ),
                ),
            )
            assertEquals(80f, scroll.scrollY / density, 0.51f)
            assertEquals(
                80f,
                (events.last { it.name == "scroll_metrics" }
                    .payload.getValue("offset_y") as Number).toFloat(),
                0.51f,
            )
            assertEquals(
                Renderer.ApplyResult.REJECTED_KNOWN,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        3,
                        listOf(RenderOperation.ScrollTo(2, 0f, 1f, false)),
                    ),
                ),
            )
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun removedCellViewsArePooledAndReused() {
        val renderer = Renderer(context, {})
        try {
            val operations = mutableListOf<RenderOperation>(
                RenderOperation.Create(1, "Layout"),
                RenderOperation.SetProps(
                    1,
                    mapOf("orientation" to "vertical", "width" to 200, "height" to 300),
                ),
            )
            for ((boxId, description, text) in listOf(
                Triple(3, "cell-1", "one"),
                Triple(5, "cell-2", "two"),
            )) {
                operations += RenderOperation.Create(boxId, "Box")
                operations += RenderOperation.SetProps(
                    boxId,
                    mapOf(
                        "width" to 200,
                        "height" to 100,
                        "content_description" to description,
                    ),
                )
                operations += RenderOperation.Create(boxId + 1, "Text")
                operations += RenderOperation.SetProps(boxId + 1, mapOf("text" to text))
                operations += RenderOperation.InsertChild(boxId, boxId + 1, 0)
                operations += RenderOperation.InsertChild(1, boxId, (boxId - 3) / 2)
            }
            operations += RenderOperation.InsertChild(0, 1, 0)
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(RenderTransaction(1, operations)),
            )
            val cell2Box = renderer.viewForTest(5)
            val cell2Text = renderer.viewForTest(6)
            assertNotNull(cell2Box)
            assertNotNull(cell2Text)

            // Removing cell 2 pools its Box and Text.
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        2,
                        listOf(
                            RenderOperation.RemoveChild(1, 5),
                            RenderOperation.Remove(5),
                        ),
                    ),
                ),
            )
            assertEquals(2, renderer.recycledViewCount)

            // Creating a third cell reuses the exact pooled instances.
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        3,
                        listOf(
                            RenderOperation.Create(7, "Box"),
                            RenderOperation.SetProps(
                                7,
                                mapOf(
                                    "width" to 200,
                                    "height" to 100,
                                    "content_description" to "cell-3",
                                ),
                            ),
                            RenderOperation.Create(8, "Text"),
                            RenderOperation.SetProps(8, mapOf("text" to "three")),
                            RenderOperation.InsertChild(7, 8, 0),
                            RenderOperation.InsertChild(1, 7, 1),
                        ),
                    ),
                ),
            )
            assertEquals(0, renderer.recycledViewCount)
            assertSame(cell2Box, renderer.viewForTest(7))
            assertSame(cell2Text, renderer.viewForTest(8))
            // The stale cell-2 props were reset and the new props applied.
            assertEquals("cell-3", renderer.viewForTest(7)?.contentDescription)
            assertEquals("three", (renderer.viewForTest(8) as TextView).text.toString())
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun semanticContentExtentRollsBackAndResetsOnPooledReuse() {
        val renderer = Renderer(context, {})
        try {
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        1,
                        listOf(
                            RenderOperation.Create(1, "Scroll"),
                            RenderOperation.SetProps(1, mapOf("width" to 200, "height" to 100)),
                            RenderOperation.Create(2, "Box"),
                            RenderOperation.SetProps(
                                2,
                                mapOf(
                                    "_virtual_content_width" to 200,
                                    "_virtual_content_height" to 500,
                                ),
                            ),
                            RenderOperation.InsertChild(1, 2, 0),
                            RenderOperation.InsertChild(0, 1, 0),
                        ),
                    ),
                ),
            )
            val density = renderer.root.resources.displayMetrics.density
            val original = renderer.viewForTest(2) as RoundedFrameLayout
            assertEquals((500 * density).toInt(), original.virtualContentHeightPx)

            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(
                        RenderOperation.SetProp(2, "_virtual_content_height", 100),
                        RenderOperation.Create(3, "Box"),
                        RenderOperation.InsertChild(1, 3, 1),
                    ),
                ),
            )
            assertEquals(Renderer.ApplyResult.PARTIAL, result)
            assertEquals((500 * density).toInt(), original.virtualContentHeightPx)

            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        3,
                        listOf(
                            RenderOperation.RemoveChild(0, 1),
                            RenderOperation.Remove(1),
                            RenderOperation.Create(4, "Box"),
                            RenderOperation.InsertChild(0, 4, 0),
                        ),
                    ),
                ),
            )
            val reused = renderer.viewForTest(4) as RoundedFrameLayout
            assertSame(original, reused)
            assertEquals(0, reused.virtualContentWidthPx)
            assertEquals(0, reused.virtualContentHeightPx)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun interactiveScrollbarRollsBackAndResetsOnRemoval() {
        val renderer = Renderer(context, {})
        try {
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        1,
                        listOf(
                            RenderOperation.Create(1, "Scroll"),
                            RenderOperation.SetProps(
                                1,
                                mapOf(
                                    "width" to 200,
                                    "height" to 100,
                                    "interactive_scrollbar" to true,
                                ),
                            ),
                            RenderOperation.Create(2, "Layout"),
                            RenderOperation.SetProps(
                                2,
                                mapOf(
                                    "orientation" to "vertical",
                                    "width" to 200,
                                    "height" to 300,
                                ),
                            ),
                            RenderOperation.InsertChild(1, 2, 0),
                            RenderOperation.InsertChild(0, 1, 0),
                        ),
                    ),
                ),
            )
            val original = renderer.viewForTest(1) as RoundedScrollView
            assertTrue(original.interactiveScrollbarEnabled)
            assertFalse(original.isVerticalScrollBarEnabled)

            // The second direct Scroll child fails during apply. Rollback must
            // restore the interactive prop changed earlier in this transaction.
            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(
                        RenderOperation.SetProp(1, "interactive_scrollbar", false),
                        RenderOperation.Create(3, "Box"),
                        RenderOperation.InsertChild(1, 3, 1),
                    ),
                ),
            )
            assertEquals(Renderer.ApplyResult.PARTIAL, result)
            assertTrue(original.interactiveScrollbarEnabled)
            assertFalse(original.isVerticalScrollBarEnabled)

            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        3,
                        listOf(
                            RenderOperation.RemoveChild(0, 1),
                            RenderOperation.Remove(1),
                            RenderOperation.Create(4, "Scroll"),
                            RenderOperation.InsertChild(0, 4, 0),
                        ),
                    ),
                ),
            )
            // Scroll hosts are not cell-pooled. A fresh host starts from the
            // passive native scrollbar default; cell pooling remains limited
            // to reusable cell view kinds.
            val fresh = renderer.viewForTest(4) as RoundedScrollView
            assertFalse(fresh.interactiveScrollbarEnabled)
            assertTrue(fresh.isVerticalScrollBarEnabled)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun rolledBackCellReuseRestoresTheOriginalTreeExactly() {
        val renderer = Renderer(context, {})
        try {
            val operations = mutableListOf<RenderOperation>(
                RenderOperation.Create(1, "Scroll"),
                RenderOperation.SetProps(1, mapOf("width" to 200, "height" to 100)),
                RenderOperation.Create(2, "Layout"),
                RenderOperation.SetProps(
                    2,
                    mapOf("orientation" to "vertical", "width" to 200, "height" to 300),
                ),
            )
            for ((boxId, description, text) in listOf(
                Triple(3, "cell-1", "one"),
                Triple(5, "cell-2", "two"),
            )) {
                operations += RenderOperation.Create(boxId, "Box")
                operations += RenderOperation.SetProps(
                    boxId,
                    mapOf(
                        "width" to 200,
                        "height" to 100,
                        "content_description" to description,
                    ),
                )
                operations += RenderOperation.Create(boxId + 1, "Text")
                operations += RenderOperation.SetProps(boxId + 1, mapOf("text" to text))
                operations += RenderOperation.InsertChild(boxId, boxId + 1, 0)
                operations += RenderOperation.InsertChild(2, boxId, (boxId - 3) / 2)
            }
            operations += RenderOperation.InsertChild(1, 2, 0)
            operations += RenderOperation.InsertChild(0, 1, 0)
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(RenderTransaction(1, operations)),
            )

            // Remove cell 2 (pools its views), create cell 3 reusing them,
            // then a second child in the Scroll fails at apply -> rollback.
            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    2,
                    listOf(
                        RenderOperation.RemoveChild(2, 5),
                        RenderOperation.Remove(5),
                        RenderOperation.Create(7, "Box"),
                        RenderOperation.SetProps(
                            7,
                            mapOf(
                                "width" to 200,
                                "height" to 100,
                                "content_description" to "cell-3",
                            ),
                        ),
                        RenderOperation.Create(8, "Text"),
                        RenderOperation.SetProps(8, mapOf("text" to "three")),
                        RenderOperation.InsertChild(7, 8, 0),
                        RenderOperation.InsertChild(2, 7, 1),
                        RenderOperation.Create(9, "Box"),
                        RenderOperation.InsertChild(1, 9, 1),
                    ),
                ),
            )
            assertEquals(Renderer.ApplyResult.PARTIAL, result)

            // The original tree is restored with its props; the pooled views
            // were popped back and the failed create's view returned to the pool.
            assertEquals("cell-2", renderer.viewForTest(5)?.contentDescription)
            assertEquals("two", (renderer.viewForTest(6) as TextView).text.toString())
            assertEquals(null, renderer.viewForTest(7))
            assertEquals(null, renderer.viewForTest(8))
            assertEquals(1, renderer.recycledViewCount)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun roundedScrollClipTracksTheVisibleViewport() {
        val renderer = Renderer(context, {})
        try {
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        1,
                        listOf(
                            RenderOperation.Create(1, "Scroll"),
                            RenderOperation.SetProps(
                                1,
                                mapOf(
                                    "width" to 100,
                                    "height" to 100,
                                    "corner_radius_top_left" to 12,
                                    "corner_radius_top_right" to 12,
                                    "corner_radius_bottom_left" to 12,
                                    "corner_radius_bottom_right" to 12,
                                ),
                            ),
                            RenderOperation.Create(2, "Box"),
                            RenderOperation.SetProps(
                                2,
                                mapOf(
                                    "width" to 100,
                                    "height" to 300,
                                    "_virtual_content_width" to 100,
                                    "_virtual_content_height" to 300,
                                ),
                            ),
                            RenderOperation.Create(3, "Box"),
                            RenderOperation.SetProps(
                                3,
                                mapOf(
                                    "width" to 100,
                                    "height" to 100,
                                    "translation_y" to 200,
                                    "background_color" to "#FF0000",
                                ),
                            ),
                            RenderOperation.InsertChild(2, 3, 0),
                            RenderOperation.InsertChild(1, 2, 0),
                            RenderOperation.InsertChild(0, 1, 0),
                        ),
                    ),
                ),
            )

            val density = renderer.root.resources.displayMetrics.density
            val extent = (100 * density).toInt()
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec(extent, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(extent, View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, extent, extent)
            val scroll = renderer.root.getChildAt(0) as RoundedScrollView
            val bitmap = Bitmap.createBitmap(extent, extent, Bitmap.Config.ARGB_8888)
            scroll.scrollTo(0, (200 * density).toInt())
            assertEquals((200 * density).toInt(), scroll.scrollY)
            scroll.draw(Canvas(bitmap))
            val clipBounds = RectF()
            scroll.clipPath.computeBounds(clipBounds, true)
            assertEquals(scroll.scrollY.toFloat(), clipBounds.top, 0.5f)
            assertEquals((scroll.scrollY + scroll.height).toFloat(), clipBounds.bottom, 0.5f)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun virtualListScrollsFreelyAndReportsProjection() {
        val renderer = Renderer(context, {})
        try {
            val operations = mutableListOf<RenderOperation>(
                RenderOperation.Create(1, "Scroll"),
                RenderOperation.SetProps(
                    1,
                    mapOf(
                        "width" to 200,
                        "height" to 100,
                        "_virtual_list_initial_offset" to 250,
                    ),
                ),
                RenderOperation.Create(2, "Layout"),
                RenderOperation.SetProps(
                    2,
                    mapOf(
                        "orientation" to "vertical",
                        "width" to 200,
                        "height" to 500,
                    ),
                ),
            )
            for (index in 0 until 5) {
                val id = 3 + index
                operations += RenderOperation.Create(id, "Box")
                operations += RenderOperation.SetProps(
                    id,
                    mapOf(
                        "width" to 200,
                        "height" to 100,
                    ),
                )
                operations += RenderOperation.InsertChild(2, id, index)
            }
            operations += RenderOperation.InsertChild(1, 2, 0)
            operations += RenderOperation.InsertChild(0, 1, 0)
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(RenderTransaction(1, operations)),
            )

            val density = renderer.root.resources.displayMetrics.density
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((200 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)
            val scroll = renderer.root.getChildAt(0) as RoundedScrollView
            assertEquals(250f, scroll.scrollY / density, 0.51f)

            // Free scrolling is never clamped to an acknowledged region; only
            // the native content bounds apply (500 content - 100 viewport).
            // Tolerance 1dp: emulator density 2.625 rounds a clamp to ±2px.
            scroll.scrollTo(0, (450 * density).toInt())
            assertEquals(400f, scroll.scrollY / density, 1.0f)

            // Python-driven targets become the reported projection.
            scroll.smoothScrollToPosition(0, (300 * density).toInt())
            assertEquals(300f, scroll.virtualListProjection.second / density, 0.51f)
            scroll.scrollToPosition(0, (150 * density).toInt())
            assertEquals(150f, scroll.scrollY / density, 0.51f)
            assertEquals(150f, scroll.virtualListProjection.second / density, 0.51f)

            // A new touch gesture resets the projection to the current position.
            val down = MotionEvent.obtain(
                1L,
                1L,
                MotionEvent.ACTION_DOWN,
                10f,
                10f,
                0,
            )
            scroll.dispatchTouchEvent(down)
            down.recycle()
            assertEquals(
                scroll.scrollY.toFloat(),
                scroll.virtualListProjection.second.toFloat(),
                0.51f,
            )
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun horizontalScrollReportsMetricsAndAcceptsProgrammaticOffset() {
        val events = mutableListOf<NativeEvent>()
        val renderer = Renderer(context, events::add)
        try {
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        1,
                        listOf(
                            RenderOperation.Create(1, "HorizontalScroll"),
                            RenderOperation.SetProps(
                                1,
                                mapOf("width" to 100, "height" to 100),
                            ),
                            RenderOperation.Create(2, "Box"),
                            RenderOperation.SetProps(
                                2,
                                mapOf("width" to 500, "height" to 100),
                            ),
                            RenderOperation.InsertChild(1, 2, 0),
                            RenderOperation.Listen(1, "scroll_metrics", 11, "latest"),
                            RenderOperation.InsertChild(0, 1, 0),
                        ),
                    ),
                ),
            )
            val density = renderer.root.resources.displayMetrics.density
            renderer.root.measure(
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec((100 * density).toInt(), View.MeasureSpec.EXACTLY),
            )
            renderer.root.layout(0, 0, renderer.root.measuredWidth, renderer.root.measuredHeight)
            val scroll = renderer.root.getChildAt(0) as HorizontalScrollView
            val content = scroll.getChildAt(0)
            content.layout(
                0,
                0,
                (500 * density).toInt(),
                (100 * density).toInt(),
            )
            scroll.scrollTo((60 * density).toInt(), 0)

            val event = events.last { it.name == "scroll_metrics" }
            assertEquals(60f, (event.payload.getValue("offset_x") as Number).toFloat(), 0.51f)
            assertEquals(100f, (event.payload.getValue("viewport_width") as Number).toFloat(), 0.51f)
            assertEquals(500f, (event.payload.getValue("content_width") as Number).toFloat(), 0.51f)

            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        2,
                        listOf(RenderOperation.ScrollTo(1, 80f, 0f, false)),
                    ),
                ),
            )
            assertEquals(80f, scroll.scrollX / density, 0.51f)
            assertEquals(
                80f,
                (events.last { it.name == "scroll_metrics" }
                    .payload.getValue("offset_x") as Number).toFloat(),
                0.51f,
            )
        } finally {
            renderer.dispose()
        }
    }

    private fun withMounted(
        kind: String,
        props: Map<String, Any?> = emptyMap(),
        assertion: (View, Renderer) -> Unit,
    ) {
        val renderer = Renderer(context, {})
        try {
            val operations = mutableListOf<RenderOperation>()
            operations += RenderOperation.Create(1, kind)
            if (props.isNotEmpty()) {
                operations += RenderOperation.SetProps(1, props)
            }
            operations += RenderOperation.InsertChild(0, 1, 0)
            assertEquals(
                Renderer.ApplyResult.OK,
                renderer.applyDirectTransaction(RenderTransaction(1, operations)),
            )
            assertion(renderer.root.getChildAt(0), renderer)
        } finally {
            renderer.dispose()
        }
    }
}
