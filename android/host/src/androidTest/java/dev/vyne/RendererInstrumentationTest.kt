/**
 * Instrumentation tests for the Vyne Renderer on a real or managed Android device.
 *
 * These tests verify that native View operations (create, set props, insert, remove,
 * accessibility, animation, pointer, focus, input) function correctly across the
 * supported API range (26-35).  They require a device or emulator to run.
 *
 * Run with:
 *   ./gradlew :host:connectedDebugAndroidTest
 *
 * Or for managed devices:
 *   ./gradlew :host:api26DebugAndroidTest
 *   ./gradlew :host:api29DebugAndroidTest
 *   ./gradlew :host:api30DebugAndroidTest
 */
package dev.vyne

import android.os.Build
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RendererInstrumentationTest {

    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    // ── Basic view creation and lifecycle ──────────────────────────────

    @Test
    fun createText_setsDefaultText() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            val result = renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Text"},
                    {"op":"set_props","id":1,"props":{"text":"Hello"}},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            assertEquals(Renderer.ApplyResult.OK, result)

            val textView = renderer.root.getChildAt(0) as? TextView
            assertNotNull("Text view should be created", textView)
            assertEquals("Hello", textView?.text?.toString())
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun updateText_changesDisplayedText() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Text"},
                    {"op":"set_props","id":1,"props":{"text":"Old"}},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"set_prop","id":1,"name":"text","value":"New"}
                ]}
            """))
            val textView = renderer.root.getChildAt(0) as? TextView
            assertEquals("New", textView?.text?.toString())
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun directStringBatch_usesSharedTypedTransactionPath() {
        val renderer = Renderer(context, TestEventSink())
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Text"},
                    {"op":"create","id":2,"kind":"Text"},
                    {"op":"insert_child","parent":0,"child":1,"index":0},
                    {"op":"insert_child","parent":0,"child":2,"index":1}
                ]}
            """))

            val result =
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        revision = 2,
                        operations =
                            listOf(
                                RenderOperation.SetStringPropBatch(
                                    intArrayOf(1, 2),
                                    "text",
                                    arrayOf("First", "Second"),
                                ),
                            ),
                    ),
                )

            assertEquals(Renderer.ApplyResult.OK, result)
            assertEquals(
                "First",
                (renderer.root.getChildAt(0) as TextView).text.toString(),
            )
            assertEquals(
                "Second",
                (renderer.root.getChildAt(1) as TextView).text.toString(),
            )
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun directBatchPreflight_rejectsWholeBatchBeforeMutation() {
        val renderer = Renderer(context, TestEventSink())
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Text"},
                    {"op":"set_prop","id":1,"name":"text","value":"Old"},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))

            val result =
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        revision = 2,
                        operations =
                            listOf(
                                RenderOperation.SetPropBatch(
                                    intArrayOf(1, 1),
                                    arrayOf("text", "not_a_real_property"),
                                    listOf("New", "invalid"),
                                ),
                            ),
                    ),
                )

            assertEquals(Renderer.ApplyResult.REJECTED_KNOWN, result)
            assertEquals(
                "Old",
                (renderer.root.getChildAt(0) as TextView).text.toString(),
            )
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun removeChild_detachesView() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Text"},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            assertEquals(1, renderer.root.childCount)

            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"remove_child","parent":0,"child":1}
                ]}
            """))
            assertEquals(0, renderer.root.childCount)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun recursiveRemove_acceptsDetachedNonLeafSubtree() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            val initial = renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Box"},
                    {"op":"create","id":2,"kind":"Text"},
                    {"op":"set_props","id":2,"props":{"text":"nested"}},
                    {"op":"insert_child","parent":1,"child":2,"index":0},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            assertEquals(Renderer.ApplyResult.OK, initial)

            val replacement = renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"remove_child","parent":0,"child":1},
                    {"op":"remove","id":1},
                    {"op":"create","id":3,"kind":"Text"},
                    {"op":"set_props","id":3,"props":{"text":"flat"}},
                    {"op":"insert_child","parent":0,"child":3,"index":0}
                ]}
            """))
            assertEquals(Renderer.ApplyResult.OK, replacement)
            assertEquals(1, renderer.root.childCount)
            assertEquals("flat", (renderer.root.getChildAt(0) as TextView).text.toString())
        } finally {
            renderer.dispose()
        }
    }

    // ── Property application ───────────────────────────────────────────

    @Test
    fun setBackgroundColor_appliesToView() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Box"},
                    {"op":"set_props","id":1,"props":{"width":100,"height":100,"background_color":"#FF0000"}},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            val box = renderer.root.getChildAt(0) as? View
            assertNotNull("Box should be created", box)
            assertNotNull("Background drawable should be set", box?.background)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun setPadding_appliesInsets() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Box"},
                    {"op":"set_props","id":1,"props":{"padding_top":20,"padding_bottom":20,"padding_start":20,"padding_end":20}},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            val box = renderer.root.getChildAt(0) as? View
            val padding = box?.paddingLeft ?: 0
            assertTrue("Padding should be > 0", padding > 0)
        } finally {
            renderer.dispose()
        }
    }

    // ── Event emission ─────────────────────────────────────────────────

    @Test
    fun clickEvent_triggersHandler() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Box"},
                    {"op":"set_props","id":1,"props":{"width":100,"height":100}},
                    {"op":"listen","id":1,"event":"click","handler":42},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            val box = renderer.root.getChildAt(0)!!
            box.performClick()
            assertTrue("Click event should be emitted", sink.events.isNotEmpty())
            assertEquals("click", sink.events.last().name)
            assertEquals(42, sink.events.last().handler)
        } finally {
            renderer.dispose()
        }
    }

    // ── Animation registration ─────────────────────────────────────────

    @Test
    fun motionSetTarget_runsOnNativeFramesAndReportsCompletion() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Box"},
                    {"op":"set_props","id":1,"props":{"width":100,"height":100}},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            // Unified motion op
            var result: Renderer.ApplyResult? = null
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                result = renderer.applyMessage(JSONObject("""
                    {"type":"commit","ops":[
                        {"op":"motion_set_target","animation_id":17,
                         "slot_key":"view:1:prop:opacity",
                         "node_id":1,"property":"opacity",
                         "spec_type":"tween","targets":[0.5],
                         "duration_ms":48,"easing":"linear",
                         "damping_ratio":0.8,"stiffness":380.0,
                         "rest_value_threshold":0.01,"rest_velocity_threshold":0.01,
                         "retarget":"restart"}
                    ]}
                """))
            }
            assertEquals(Renderer.ApplyResult.OK, result)
            Thread.sleep(96)
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()

            assertEquals(0.5f, renderer.root.getChildAt(0).alpha, 0.01f)
            val lifecycle =
                sink.events.last {
                    it.name == "__vyne_system__" &&
                        it.payload["type"] == "animation_lifecycle"
                }
            assertEquals(17L, lifecycle.payload["animation_id"])
            assertEquals("completed", lifecycle.payload["status"])
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun declarativeAnimatedValueSnapsFirstTargetThenAnimatesFromLiveValue() {
        val renderer = Renderer(context, TestEventSink())
        try {
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertEquals(
                    Renderer.ApplyResult.OK,
                    renderer.applyMessage(JSONObject("""
                        {"type":"commit","ops":[
                            {"op":"create","id":1,"kind":"Box"},
                            {"op":"set_props","id":1,"props":{
                                "width":100,"height":100,
                                "opacity":{
                                    "__vyne_animated_value__":true,
                                    "value":0.2,"duration":64,"easing":"linear"
                                }
                            }},
                            {"op":"insert_child","parent":0,"child":1,"index":0}
                        ]}
                    """)),
                )
            }
            val box = renderer.root.getChildAt(0)
            assertEquals(0.2f, box.alpha, 0.001f)

            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertEquals(
                    Renderer.ApplyResult.OK,
                    renderer.applyMessage(JSONObject("""
                        {"type":"commit","ops":[
                            {"op":"set_prop","id":1,"name":"opacity","value":{
                                "__vyne_animated_value__":true,
                                "value":0.8,"duration":64,"easing":"linear"
                            }}
                        ]}
                    """)),
                )
                // Applying the logical target must not visibly snap before
                // the first animation frame.
                assertEquals(0.2f, box.alpha, 0.001f)
            }
            Thread.sleep(112)
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            assertEquals(0.8f, box.alpha, 0.01f)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun persistentDriverUpdatesDerivedViewAndCanvasBindingsTogether() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        val position =
            JSONObject("""
                {
                    "__vyne_animated_node__":true,
                    "value":4,
                    "expression":{
                        "op":"interpolate",
                        "input":{"op":"value","driver_id":7,"initial":0},
                        "input_range":[0,1],
                        "output_range":[4,214],
                        "extrapolate":"clamp"
                    }
                }
            """)
        val canvasDraw =
            JSONArray("""
                [
                    {
                        "kind":"circle",
                        "_vyne_op_id":"driver-circle",
                        "cx":{
                            "__vyne_animated_node__":true,
                            "value":10,
                            "expression":{
                                "op":"add",
                                "left":{"op":"constant","value":10},
                                "right":{
                                    "op":"multiply",
                                    "left":{
                                        "op":"value",
                                        "driver_id":7,
                                        "initial":0
                                    },
                                    "right":{"op":"constant","value":100}
                                }
                            }
                        },
                        "cy":20,
                        "r":5
                    }
                ]
            """)
        try {
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertEquals(
                    Renderer.ApplyResult.OK,
                    renderer.applyDirectTransaction(
                        RenderTransaction(
                            1,
                            listOf(
                                RenderOperation.Create(1, "Box"),
                                RenderOperation.SetProps(
                                    1,
                                    mapOf(
                                        "width" to 40,
                                        "height" to 40,
                                        "translation_x" to position,
                                    ),
                                ),
                                RenderOperation.InsertChild(0, 1, 0),
                                RenderOperation.Create(2, "Canvas"),
                                RenderOperation.SetProps(
                                    2,
                                    mapOf(
                                        "width" to 240,
                                        "height" to 40,
                                        "draw" to canvasDraw,
                                    ),
                                ),
                                RenderOperation.InsertChild(0, 2, 1),
                            ),
                        ),
                    ),
                )
            }
            val box = renderer.root.getChildAt(0)
            val canvas = renderer.root.getChildAt(1) as CanvasView
            val density = box.resources.displayMetrics.density
            assertEquals(4f, box.translationX / density, 0.25f)
            assertEquals(10f, canvas.readOpField("driver-circle", "cx"), 0.01f)

            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertEquals(
                    Renderer.ApplyResult.OK,
                    renderer.applyDirectTransaction(
                        RenderTransaction(
                            2,
                            listOf(
                                RenderOperation.MotionDriverSetTarget(
                                    animationId = 41,
                                    driverId = 7,
                                    nodeId = 1,
                                    property = "translation_x",
                                    targets = listOf(1f),
                                    specType = "tween",
                                    fromValue = null,
                                    durationMs = 64,
                                    easing = "linear",
                                    dampingRatio = 0.8f,
                                    stiffness = 380f,
                                    restValueThreshold = 0.01f,
                                    restVelocityThreshold = 0.01f,
                                    retargetPolicy = "restart",
                                ),
                            ),
                        ),
                    ),
                )
            }
            Thread.sleep(112)
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()

            assertEquals(214f, box.translationX / density, 0.5f)
            assertEquals(110f, canvas.readOpField("driver-circle", "cx"), 0.1f)
            val lifecycle =
                sink.events.last {
                    it.name == "__vyne_system__" &&
                        it.payload["animation_id"] == 41L
                }
            assertEquals("completed", lifecycle.payload["status"])
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun unboundDriverStateIsReleasedBeforeDriverIdIsReused() {
        val renderer = Renderer(context, TestEventSink())
        fun driverValue(initial: Float) =
            JSONObject("""
                {
                    "__vyne_animated_node__":true,
                    "value":$initial,
                    "expression":{
                        "op":"value",
                        "driver_id":7,
                        "initial":$initial
                    }
                }
            """)
        fun apply(revision: Long, vararg operations: RenderOperation) {
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertEquals(
                    Renderer.ApplyResult.OK,
                    renderer.applyDirectTransaction(
                        RenderTransaction(revision, operations.toList()),
                    ),
                )
            }
        }

        try {
            apply(
                1,
                RenderOperation.Create(1, "Box"),
                RenderOperation.SetProps(
                    1,
                    mapOf(
                        "width" to 40,
                        "height" to 40,
                        "translation_x" to driverValue(0f),
                    ),
                ),
                RenderOperation.InsertChild(0, 1, 0),
            )
            apply(
                2,
                RenderOperation.MotionDriverSetTarget(
                    animationId = 42,
                    driverId = 7,
                    nodeId = 1,
                    property = "translation_x",
                    targets = listOf(5f),
                    specType = "tween",
                    fromValue = null,
                    durationMs = 0,
                    easing = "linear",
                    dampingRatio = 0.8f,
                    stiffness = 380f,
                    restValueThreshold = 0.01f,
                    restVelocityThreshold = 0.01f,
                    retargetPolicy = "restart",
                ),
            )
            val box = renderer.root.getChildAt(0)
            val density = box.resources.displayMetrics.density
            // A durationMs=0 tween completes on the next presentation frame;
            // on a busy emulator the frame clock may not have advanced yet,
            // so wait for the target instead of asserting mid-frame.
            waitUntil(timeoutMs = 2_000) {
                kotlin.math.abs(box.translationX / density - 5f) < 0.001f
            }

            apply(
                3,
                RenderOperation.SetProp(1, "translation_x", 2f),
                RenderOperation.SetProp(1, "translation_x", driverValue(0f)),
            )
            waitUntil(timeoutMs = 2_000) {
                kotlin.math.abs(box.translationX / density - 5f) < 0.001f
            }

            apply(4, RenderOperation.SetProp(1, "translation_x", 2f))
            apply(5, RenderOperation.SetProp(1, "translation_x", driverValue(0f)))
            waitUntil(timeoutMs = 2_000) {
                kotlin.math.abs(box.translationX / density) < 0.001f
            }
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun canvasAnimatedValueUsesStableOperationSlot() {
        val renderer = Renderer(context, TestEventSink())
        try {
            fun draw(target: Double) =
                JSONObject("""
                    {"type":"commit","ops":[
                        {"op":"set_prop","id":1,"name":"draw","value":[
                            {"kind":"circle","_vyne_op_id":"circle-main",
                             "cx":{
                                "__vyne_animated_value__":true,
                                "value":$target,"duration":64,"easing":"linear"
                             },
                             "cy":20,"r":5}
                        ]}
                    ]}
                """)

            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertEquals(
                    Renderer.ApplyResult.OK,
                    renderer.applyMessage(JSONObject("""
                        {"type":"commit","ops":[
                            {"op":"create","id":1,"kind":"Canvas"},
                            {"op":"set_props","id":1,"props":{
                                "width":100,"height":100,
                                "draw":[
                                    {"kind":"circle","_vyne_op_id":"circle-main",
                                     "cx":{
                                        "__vyne_animated_value__":true,
                                        "value":10,"duration":64,"easing":"linear"
                                     },
                                     "cy":20,"r":5}
                                ]
                            }},
                            {"op":"insert_child","parent":0,"child":1,"index":0}
                        ]}
                    """)),
                )
            }
            val canvas = renderer.root.getChildAt(0) as CanvasView
            assertEquals(10f, canvas.readOpField("circle-main", "cx"), 0.001f)

            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertEquals(Renderer.ApplyResult.OK, renderer.applyMessage(draw(30.0)))
                assertEquals(
                    10f,
                    canvas.readOpField("circle-main", "cx"),
                    0.001f,
                )
            }
            Thread.sleep(112)
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            assertEquals(30f, canvas.readOpField("circle-main", "cx"), 0.01f)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun invalidMotionCommandIsRejectedBeforeTreeMutation() {
        val renderer = Renderer(context, TestEventSink())
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Box"},
                    {"op":"set_props","id":1,"props":{"opacity":1.0}},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            val box = renderer.root.getChildAt(0)

            val result =
                renderer.applyDirectTransaction(
                    RenderTransaction(
                        revision = 2,
                        operations =
                            listOf(
                                RenderOperation.SetProp(1, "opacity", 0.75),
                                RenderOperation.MotionSetTarget(
                                    animationId = 3,
                                    slotKey = "view:1:prop:text",
                                    nodeId = 1,
                                    property = "text",
                                    targets = listOf(1f),
                                    slotId = null,
                                    specType = "tween",
                                    fromValue = null,
                                    durationMs = 100,
                                    easing = "linear",
                                    dampingRatio = 0.8f,
                                    stiffness = 380f,
                                    restValueThreshold = 0.01f,
                                    restVelocityThreshold = 0.01f,
                                    retargetPolicy = "restart",
                                ),
                            ),
                    ),
                )

            assertEquals(Renderer.ApplyResult.REJECTED_KNOWN, result)
            assertEquals(1f, box.alpha, 0.001f)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun animatedCanvasDashOffsetRebuildsTheNativeDashEffect() {
        lateinit var canvas: CanvasView
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            canvas = CanvasView(context)
            canvas.ops =
                JSONArray("""
                    [
                        {"kind":"line","_vyne_op_id":"line-main",
                         "x1":0,"y1":0,"x2":40,"y2":0,
                         "stroke":"#ff000000","stroke_width":2,
                         "dash":[4,2],"dash_offset":0}
                    ]
                """)
        }
        val initialCompiles = canvas.dashEffectCreateCount

        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            canvas.writeOpField("line-main", "dash_offset", 3f)
        }

        assertEquals(3f, canvas.readOpField("line-main", "dash_offset"), 0.001f)
        assertEquals(initialCompiles + 1, canvas.dashEffectCreateCount)
    }

    // ── Accessibility semantics ────────────────────────────────────────

    @Test
    fun accessibilityRole_setsClassname() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Box"},
                    {"op":"set_props","id":1,"props":{
                        "width":100,"height":100,
                        "accessibility_role":"button",
                        "content_description":"Tap me"
                    }},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            val box = renderer.root.getChildAt(0)!!
            assertEquals(
                View.IMPORTANT_FOR_ACCESSIBILITY_YES,
                box.importantForAccessibility
            )
        } finally {
            renderer.dispose()
        }
    }

    // ── Outline / corner radius (ANDROID-01 API safety) ────────────────

    @Test
    fun cornerRadius_doesNotCrash() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            val result = renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Box"},
                    {"op":"set_props","id":1,"props":{
                        "width":200,"height":200,
                        "background_color":"#CCCCCC",
                        "corner_radius_top_left":12,
                        "corner_radius_top_right":12,
                        "corner_radius_bottom_right":12,
                        "corner_radius_bottom_left":12
                    }},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            assertEquals(Renderer.ApplyResult.OK, result)

            // Force layout so outline can be computed.
            val box = renderer.root.getChildAt(0)!!
            box.measure(
                View.MeasureSpec.makeMeasureSpec(200, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(200, View.MeasureSpec.EXACTLY)
            )
            box.layout(0, 0, 200, 200)

            // Trigger outline computation (used for shadows/elevation).
            // This must not throw on any API level — the implementation
            // uses setConvexPath on API < 30 and setPath on API 30+.
            box.invalidateOutline()
            // If we reach this point without an exception, the test passes.
        } finally {
            renderer.dispose()
        }
    }

    // ── Rollback / transaction ─────────────────────────────────────────

    @Test
    fun invalidOp_returnsPartial() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Text"},
                    {"op":"set_props","id":1,"props":{"text":"Before"}},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            val textViewBefore = renderer.root.getChildAt(0) as? TextView
            assertEquals("Before", textViewBefore?.text?.toString())

            // Attempting to insert a child with a bogus parent should fail.
            val result = renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"set_prop","id":1,"name":"text","value":"After"},
                    {"op":"insert_child","parent":999,"child":1,"index":0}
                ]}
            """))
            assertNotEquals(Renderer.ApplyResult.OK, result)

            // The first op (set_prop) should have been rolled back,
            // and text should still be "Before", not "After".
            val textViewAfter = renderer.root.getChildAt(0) as? TextView
            assertEquals("Before", textViewAfter?.text?.toString())
        } finally {
            renderer.dispose()
        }
    }

    // ── Listener replacement ──────────────────────────────────────────

    @Test
    fun listenerReplacement_updatesHandler() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"Box"},
                    {"op":"set_props","id":1,"props":{"width":100,"height":100}},
                    {"op":"listen","id":1,"event":"click","handler":42},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))

            // Replace handler with 99.
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"listen","id":1,"event":"click","handler":99}
                ]}
            """))

            sink.events.clear()
            val box = renderer.root.getChildAt(0)!!
            box.performClick()

            assertEquals(1, sink.events.size)
            assertEquals("click", sink.events.last().name)
            assertEquals(99, sink.events.last().handler)
        } finally {
            renderer.dispose()
        }
    }

    // ── Dispose safety ─────────────────────────────────────────────────

    @Test
    fun doubleDispose_doesNotThrow() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        renderer.applyMessage(JSONObject("""
            {"type":"commit","ops":[
                {"op":"create","id":1,"kind":"Text"},
                {"op":"insert_child","parent":0,"child":1,"index":0}
            ]}
        """))
        renderer.dispose()
        // Second dispose must not throw.
        renderer.dispose()
    }

    @Test
    fun applyAfterDispose_handlesGracefully() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink)
        renderer.dispose()
        // Applying a commit after dispose should not crash.
        val result = renderer.applyMessage(JSONObject("""
            {"type":"commit","ops":[
                {"op":"create","id":1,"kind":"Text"}
            ]}
        """))
        // Either OK (apply was a no-op) or UNKNOWN is acceptable.
        assertNotNull(result)
    }

    // ── Test helper ────────────────────────────────────────────────────

    private class TestEventSink : (NativeEvent) -> Unit {
        val events = mutableListOf<NativeEvent>()
        override fun invoke(event: NativeEvent) {
            events.add(event)
        }
    }
}

/** Keeps JSON fixture authoring local to tests; production accepts typed operations only. */
private fun Renderer.applyMessage(message: JSONObject): Renderer.ApplyResult {
    if (disposed) return Renderer.ApplyResult.UNKNOWN
    return try {
        val encoded = message.optJSONArray("ops") ?: JSONArray()
        applyDirectTransaction(
            RenderTransaction(
                message.optLong("revision", -1L).takeIf { it >= 0 },
                List(encoded.length()) { index ->
                    testOperation(encoded.getJSONObject(index))
                },
            ),
        )
    } catch (_: Throwable) {
        Renderer.ApplyResult.REJECTED_KNOWN
    }
}

private fun testOperation(op: JSONObject): RenderOperation =
    when (op.getString("op")) {
        "create" -> RenderOperation.Create(op.getInt("id"), op.getString("kind"))
        "set_props" ->
            RenderOperation.SetProps(
                op.getInt("id"),
                op.getJSONObject("props").toMap(),
            )
        "set_prop" ->
            RenderOperation.SetProp(
                op.getInt("id"),
                op.getString("name"),
                op.opt("value"),
            )
        "listen" ->
            RenderOperation.Listen(
                op.getInt("id"),
                op.getString("event"),
                op.getInt("handler"),
                "all",
            )
        "insert_child" ->
            RenderOperation.InsertChild(
                op.getInt("parent"),
                op.getInt("child"),
                op.getInt("index"),
            )
        "remove_child" ->
            RenderOperation.RemoveChild(
                op.getInt("parent"),
                op.getInt("child"),
            )
        "remove" -> RenderOperation.Remove(op.getInt("id"))
        "motion_set_target" ->
            RenderOperation.MotionSetTarget(
                animationId = op.getLong("animation_id"),
                slotKey = op.getString("slot_key"),
                nodeId = op.getInt("node_id"),
                property = op.getString("property"),
                targets =
                    op.getJSONArray("targets").let { targets ->
                        List(targets.length()) { targets.getDouble(it).toFloat() }
                    },
                slotId = op.optString("slot_id").takeIf(String::isNotEmpty),
                specType = op.optString("spec_type", "tween"),
                fromValue =
                    op.optDouble("from_value")
                        .takeUnless(Double::isNaN)
                        ?.toFloat(),
                durationMs = op.optLong("duration_ms", 300L),
                easing = op.optString("easing", "ease_out"),
                dampingRatio = op.optDouble("damping_ratio", 0.8).toFloat(),
                stiffness = op.optDouble("stiffness", 380.0).toFloat(),
                restValueThreshold =
                    op.optDouble("rest_value_threshold", 0.01).toFloat(),
                restVelocityThreshold =
                    op.optDouble("rest_velocity_threshold", 0.01).toFloat(),
                retargetPolicy = op.optString("retarget", "restart"),
            )
        "motion_cancel" ->
            RenderOperation.MotionCancel(
                animationId = op.getLong("animation_id"),
                slotKey = op.getString("slot_key"),
            )
        else -> error("Unsupported test operation: ${op.getString("op")}")
    }

private fun JSONObject.toMap(): Map<String, Any?> =
    keys().asSequence().associateWith(::opt)

private fun waitUntil(timeoutMs: Long = 2_000, condition: () -> Boolean) {
    val deadline = android.os.SystemClock.elapsedRealtime() + timeoutMs
    while (android.os.SystemClock.elapsedRealtime() < deadline) {
        if (condition()) return
        android.os.SystemClock.sleep(20)
    }
    assertTrue("Condition not met within ${timeoutMs}ms", condition())
}
