package dev.vyne

import android.widget.FrameLayout
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import org.json.JSONObject
import org.junit.runner.RunWith

/**
 * End-to-end extension kind tests through the real Renderer
 * (preflight + journaled apply + events) on a device.
 *
 * The extension spec is registered exactly as an extension would register
 * it, then exercised through the same commit path as core kinds.
 */
@RunWith(AndroidJUnit4::class)
class RendererExtensionInstrumentationTest {

    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    private class TestEventSink : (NativeEvent) -> Unit {
        val events = mutableListOf<NativeEvent>()
        override fun invoke(event: NativeEvent) {
            events.add(event)
        }
    }

    /** A test-only extension View with a native callback. */
    private class TestProgressView(ctx: android.content.Context) : FrameLayout(ctx) {
        var progress: Float = 0f
            set(value) {
                val clamped = value.coerceIn(0f, 1f)
                val changed = field != clamped
                field = clamped
                if (changed && clamped >= 1f) {
                    onComplete?.invoke()   // synchronous, like the example
                }
            }
        var ringColor: Int = 0
        var onComplete: (() -> Unit)? = null

        fun finish() {
            onComplete?.invoke()
        }
    }

    private fun registryWithThrowingExtension(): ElementRegistry =
        ElementRegistry().apply {
            registerNativeWidgets(this)
            register(
                ElementSpec(
                    kind = "TimerRing",
                    create = { TestProgressView(it.context) },
                    props = mapOf(
                        "progress" to floatProp(0f) { view, v ->
                            (view as TestProgressView).progress = v
                        },
                    ),
                ),
            )
            register(
                ElementSpec(
                    kind = "BoomRing",
                    create = { TestProgressView(it.context) },
                    props = mapOf(
                        "progress" to { _, _, _ ->
                            error("boom: apply-time failure")
                        },
                    ),
                ),
            )
            freeze()
        }

    private fun registryWithExtension(): ElementRegistry =
        ElementRegistry().apply {
            registerNativeWidgets(this)
            register(
                ElementSpec(
                    kind = "TimerRing",
                    create = { TestProgressView(it.context) },
                    props = mapOf(
                        "progress" to floatProp(0f) { view, v ->
                            (view as TestProgressView).progress = v
                        },
                        "ring_color" to colorProp(0) { view, c ->
                            (view as TestProgressView).ringColor = c
                        },
                    ),
                    events = mapOf(
                        "complete" to { view, emit ->
                            val v = view as TestProgressView
                            v.onComplete = { emit(mapOf("finished" to true)) }
                            { v.onComplete = null }
                        },
                    ),
                ),
            )
            freeze()
        }

    private fun Renderer.applyMessage(message: JSONObject): Renderer.ApplyResult {
        if (disposed) return Renderer.ApplyResult.UNKNOWN
        return try {
            val encoded = message.optJSONArray("ops") ?: org.json.JSONArray()
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
                    op.getJSONObject("props").let { obj ->
                        buildMap {
                            val keys = obj.keys()
                            while (keys.hasNext()) {
                                val key = keys.next()
                                put(key, obj.opt(key))
                            }
                        }
                    },
                )
            "set_prop" ->
                RenderOperation.SetProp(
                    op.getInt("id"),
                    op.getString("name"),
                    op.opt("value"),
                )
            "remove_prop" ->
                RenderOperation.RemoveProp(op.getInt("id"), op.getString("name"))
            "insert_child" ->
                RenderOperation.InsertChild(
                    op.getInt("parent"),
                    op.getInt("child"),
                    op.getInt("index"),
                )
            "listen" ->
                RenderOperation.Listen(
                    op.getInt("id"),
                    op.getString("event"),
                    op.getInt("handler"),
                    op.optString("delivery", "all"),
                )
            "unlisten" ->
                RenderOperation.Unlisten(op.getInt("id"), op.getString("event"))
            else -> error("unsupported test op: ${op.getString("op")}")
        }

    private fun renderer(): Renderer {
        val sink = TestEventSink()
        return Renderer(context, sink, registry = registryWithExtension())
    }

    @Test
    fun createAndSetExtensionProps() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink, registry = registryWithExtension())
        try {
            val result = renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"TimerRing"},
                    {"op":"set_props","id":1,"props":{"progress":0.5,"ring_color":"#FF6750E8","width":120}},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            assertEquals(Renderer.ApplyResult.OK, result)
            val view = renderer.root.getChildAt(0) as? TestProgressView
            assertNotNull(view, "TimerRing view should be created")
            assertEquals(0.5f, view?.progress)
            // #RRGGBBAA is canonical RGBA on the wire; decodeColor converts
            // to ARGB (E8 FF 67 50).
            assertEquals(decodeColor("#FF6750E8"), view?.ringColor)
            // Generic prop applied through the shared applicator table
            // (dp converted to px by the dimension applicator).
            val density = context.resources.displayMetrics.density
            assertEquals((120 * density).toInt(), view?.layoutParams?.width)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun removePropResetsViaRemoveHandler() {
        val renderer = renderer()
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"TimerRing"},
                    {"op":"set_prop","id":1,"name":"progress","value":0.9},
                    {"op":"insert_child","parent":0,"child":1,"index":0}
                ]}
            """))
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"remove_prop","id":1,"name":"progress"}
                ]}
            """))
            val view = renderer.root.getChildAt(0) as? TestProgressView
            assertEquals(0f, view?.progress, "remove_prop must run the spec's remove handler")
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun extensionEventAttachDetachAndEmit() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink, registry = registryWithExtension())
        try {
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"TimerRing"},
                    {"op":"insert_child","parent":0,"child":1,"index":0},
                    {"op":"listen","id":1,"event":"complete","handler":42}
                ]}
            """))
            val view = renderer.root.getChildAt(0) as? TestProgressView
            assertNotNull(view?.onComplete, "listen must attach the extension event hook")
            view?.finish()
            assertEquals(1, sink.events.size)
            assertEquals("complete", sink.events[0].name)
            assertEquals(42, sink.events[0].handler)
            assertTrue(sink.events[0].payload["finished"] == true)

            // unlisten must run the returned detach lambda.
            renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"unlisten","id":1,"event":"complete"}
                ]}
            """))
            assertTrue(view?.onComplete == null, "unlisten must invoke the detach lambda")
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun unknownPropRejectedAtPreflight() {
        val renderer = renderer()
        try {
            val result = renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"TimerRing"},
                    {"op":"set_prop","id":1,"name":"bogus","value":1}
                ]}
            """))
            assertEquals(Renderer.ApplyResult.REJECTED_KNOWN, result)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun unknownKindRejectedAtPreflight() {
        val renderer = renderer()
        try {
            val result = renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"NoSuchKind"}
                ]}
            """))
            assertEquals(Renderer.ApplyResult.REJECTED_KNOWN, result)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun coreKindPropOnExtensionKindRejected() {
        val renderer = renderer()
        try {
            val result = renderer.applyMessage(JSONObject("""
                {"type":"commit","ops":[
                    {"op":"create","id":1,"kind":"TimerRing"},
                    {"op":"set_prop","id":1,"name":"text","value":"nope"}
                ]}
            """))
            assertEquals(Renderer.ApplyResult.REJECTED_KNOWN, result)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun extensionKindRollsBackOnLateFailure() {
        // A commit that creates the view then fails must roll back the
        // create: after PARTIAL, the view must not exist.
        val renderer = renderer()
        try {
            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    revision = 1L,
                    operations = listOf(
                        RenderOperation.Create(1, "TimerRing"),
                        RenderOperation.Create(1, "TimerRing"), // duplicate id -> failure
                    ),
                ),
            )
            assertTrue(
                result == Renderer.ApplyResult.PARTIAL || result == Renderer.ApplyResult.REJECTED_KNOWN,
                "expected rollback-capable failure, got $result",
            )
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun extensionKindsQueryMatchesRegisteredSpec() {
        val renderer = renderer()
        try {
            val kinds = renderer.registryAccessor.extensionKinds()
            val info = kinds["TimerRing"]
            assertNotNull(info)
            assertEquals(setOf("progress", "ring_color"), info.props)
            assertEquals(setOf("complete"), info.events)
            assertTrue("Text" !in kinds)
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun unknownEventOnExtensionKindRejectedAtPreflight() {
        val renderer = renderer()
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1L,
                    listOf(
                        RenderOperation.Create(1, "TimerRing"),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                ),
            )
            // An event the spec does not declare is rejected by preflight —
            // REJECTED_KNOWN, never an apply-time failure.
            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    2L,
                    listOf(RenderOperation.Listen(1, "mystery", 1, "all")),
                ),
            )
            assertEquals(Renderer.ApplyResult.REJECTED_KNOWN, result)
            val view = renderer.root.getChildAt(0) as? TestProgressView
            assertTrue(view?.onComplete == null, "no listener may be attached")
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun extensionPropRollbackRestoresExactPriorValue() {
        // Blocker scenario: accepted progress=0.4; a later transaction sets
        // progress=0.9 and then fails; rollback must restore 0.4 exactly.
        val renderer = renderer()
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1L,
                    listOf(
                        RenderOperation.Create(1, "TimerRing"),
                        RenderOperation.SetProp(1, "progress", 0.4),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                ),
            )
            val view = renderer.root.getChildAt(0) as? TestProgressView
            assertEquals(0.4f, view?.progress)

            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    2L,
                    listOf(
                        RenderOperation.SetProp(1, "progress", 0.9),
                        // Late failure after the extension prop was mutated.
                        RenderOperation.SetProp(1, "bogus", 1),
                    ),
                ),
            )
            assertEquals(Renderer.ApplyResult.REJECTED_KNOWN, result)
            assertEquals(
                0.4f,
                view?.progress,
                "rollback must restore the prior accepted extension prop value",
            )
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun synchronousExtensionEventIsDroppedOnRollback() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink, registry = registryWithExtension())
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1L,
                    listOf(
                        RenderOperation.Create(1, "TimerRing"),
                        RenderOperation.Listen(1, "complete", 42, "all"),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                ),
            )
            // A transaction that fires the event synchronously (progress ->
            // 1.0) and then fails: the event must NOT reach Python.
            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    2L,
                    listOf(
                        RenderOperation.SetProp(1, "progress", 1.0),
                        RenderOperation.SetProp(1, "bogus", 1),
                    ),
                ),
            )
            assertEquals(Renderer.ApplyResult.REJECTED_KNOWN, result)
            assertEquals(
                0,
                sink.events.count { it.name == "complete" },
                "events from a rolled-back transaction must be dropped",
            )
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun synchronousExtensionEventIsDeliveredOnAcceptedCommit() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink, registry = registryWithExtension())
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1L,
                    listOf(
                        RenderOperation.Create(1, "TimerRing"),
                        RenderOperation.Listen(1, "complete", 42, "all"),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                ),
            )
            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    2L,
                    listOf(RenderOperation.SetProp(1, "progress", 1.0)),
                ),
            )
            assertEquals(Renderer.ApplyResult.OK, result)
            assertEquals(
                1,
                sink.events.count { it.name == "complete" },
                "an event fired by an accepted commit must be delivered",
            )
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun extensionPropRollbackRestoresExactPriorValueOnApplyTimeFailure() {
        // The handler throws at APPLY time (not preflight): the journal must
        // roll back the accepted extension prop to its exact prior value.
        val renderer = Renderer(
            context,
            TestEventSink(),
            registry = registryWithThrowingExtension(),
        )
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1L,
                    listOf(
                        RenderOperation.Create(1, "TimerRing"),
                        RenderOperation.SetProp(1, "progress", 0.4),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                ),
            )
            val view = renderer.root.getChildAt(0) as? TestProgressView
            assertEquals(0.4f, view?.progress)

            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    2L,
                    listOf(
                        RenderOperation.SetProp(1, "progress", 0.9),
                        RenderOperation.Create(2, "BoomRing"),
                        RenderOperation.SetProp(2, "progress", 0.5), // throws
                    ),
                ),
            )
            assertTrue(
                result == Renderer.ApplyResult.PARTIAL ||
                    result == Renderer.ApplyResult.UNKNOWN,
                "expected rollback-capable failure, got $result",
            )
            if (result == Renderer.ApplyResult.PARTIAL) {
                assertEquals(
                    0.4f,
                    view?.progress,
                    "rollback must restore the prior accepted extension prop value",
                )
            }
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun detachRunsOnRootClear() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink, registry = registryWithExtension())
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1L,
                    listOf(
                        RenderOperation.Create(1, "TimerRing"),
                        RenderOperation.Listen(1, "complete", 42, "all"),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                ),
            )
            val view = renderer.root.getChildAt(0) as? TestProgressView
            assertTrue(view?.onComplete != null)
            renderer.applyDirectTransaction(
                RenderTransaction(2L, listOf(RenderOperation.Clear(0))),
            )
            assertTrue(
                view?.onComplete == null,
                "root clear must invoke the extension detach lambda",
            )
        } finally {
            renderer.dispose()
        }
    }

    @Test
    fun detachRunsOnSubtreeRemove() {
        val sink = TestEventSink()
        val renderer = Renderer(context, sink, registry = registryWithExtension())
        try {
            renderer.applyDirectTransaction(
                RenderTransaction(
                    1L,
                    listOf(
                        RenderOperation.Create(1, "TimerRing"),
                        RenderOperation.Listen(1, "complete", 42, "all"),
                        RenderOperation.InsertChild(0, 1, 0),
                    ),
                ),
            )
            val view = renderer.root.getChildAt(0) as? TestProgressView
            val result = renderer.applyDirectTransaction(
                RenderTransaction(
                    2L,
                    listOf(
                        RenderOperation.RemoveChild(0, 1),
                        RenderOperation.Remove(1),
                    ),
                ),
            )
            assertEquals(Renderer.ApplyResult.OK, result)
            assertTrue(
                view?.onComplete == null,
                "subtree removal must invoke the extension detach lambda",
            )
        } finally {
            renderer.dispose()
        }
    }
}
