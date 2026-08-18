package dev.vyne

import android.content.Context
import android.os.SystemClock
import android.util.Log
import com.chaquo.python.PyObject
import org.json.JSONArray
import org.json.JSONObject

/**
 * Small direct-call surface exposed to Python through Chaquopy.
 *
 * Calls arrive on the dedicated Python executor. Every logical commit enters
 * through one ``commitJson`` call carrying a compact JSON document (Python's
 * ``json.dumps``); this host decodes it with org.json into an immutable
 * transaction and posts it to the Android UI thread.
 *
 * The host is deliberately Activity-free: it only needs a UI-thread post
 * target, an aliveness check, and a Context source, so the same host can
 * drive a Renderer attached to any window (activity content, WindowManager
 * overlay) without a live Activity.
 */
internal class DirectRenderHost(
    private val uiPost: (Runnable) -> Unit,
    private val isAlive: () -> Boolean,
    private val renderer: Renderer,
    private val onCommitApplied: () -> Unit,
    private val callbackFactory: (PyObject, String, Long) -> VyneCallback,
    private val contextProvider: () -> Context,
) {
    private data class Transaction(
        val revision: Long,
        val operations: MutableList<RenderOperation> = mutableListOf(),
    )

    private data class Measurement(
        val phase: String,
        val startedNs: Long,
    )

    private var transaction: Transaction? = null
    private var measurement: Measurement? = null
    @Volatile private var commitScheduledForCall = false

    // Session identity (design-pattern #1): Python publishes the real
    // uuid4 via setSessionId before the first commit; receipts carry it
    // back so Python can reject stale-session receipts.
    @Volatile private var sessionId: String = "vyne-runtime-session"

    fun setSessionId(id: String) {
        sessionId = id
    }

    fun sessionId(): String = sessionId

    /** Return the live Context for application-owned Android integrations. */
    fun getActivity(): Context = contextProvider()

    /**
     * The extension contract query for Python: kind -> (props, events) for
     * every non-core kind in the frozen registry. Encoded as nested lists
     * so Chaquopy's Java/Python conversion is unambiguous.
     */
    fun extensionKinds(): Map<String, List<Any>> =
        renderer.registryAccessor.extensionKinds().mapValues { (_, info) ->
            listOf(
                info.props.toList(),
                info.events.toList(),
                listOf(info.container),
                info.numericProps.mapValues { (_, numeric) ->
                    listOf(numeric.default, numeric.minimum, numeric.maximum)
                },
            )
        }

    /** Wrap a Python callable in the Activity's ordered bridge-work queue. */
    fun createCallback(
        callback: PyObject,
        delivery: String,
        sampleIntervalMs: Long,
    ): VyneCallback = callbackFactory(callback, delivery, sampleIntervalMs)

    fun beginMeasurement(phase: String) {
        measurement = Measurement(phase, SystemClock.elapsedRealtimeNanos())
        commitScheduledForCall = false
    }

    fun commitScheduled(): Boolean = commitScheduledForCall

    /**
     * One JNI crossing per commit. Python sends ``{"revision": N,
     * "ops": [...]}`` as a compact JSON string; the ops are decoded in order
     * into a RenderTransaction and posted to the UI thread exactly like the
     * previous begin/ops/finish sequence. Any decode error aborts the
     * transaction and propagates to Python, which rolls back the framework.
     */
    fun commitJson(json: String) {
        val payload = JSONObject(json)
        beginCommit(payload.getLong("revision"))
        try {
            val ops = payload.getJSONArray("ops")
            for (index in 0 until ops.length()) {
                add(decodeOperation(ops.getJSONObject(index)))
            }
            finishCommit()
        } catch (error: Throwable) {
            abortCommit()
            throw error
        }
    }

    private fun beginCommit(revision: Long) {
        check(transaction == null) { "A direct commit is already active" }
        transaction = Transaction(revision)
    }

    private fun finishCommit() {
        val finished = requireNotNull(transaction) { "No direct commit is active" }
        transaction = null
        commitScheduledForCall = true
        val bridgeFinishedNs = SystemClock.elapsedRealtimeNanos()
        val commitMeasurement = measurement
        measurement = null

        uiPost {
            val applyStartedNs = SystemClock.elapsedRealtimeNanos()
            if (!isAlive() || renderer.disposed) {
                return@uiPost
            }

            val directTransaction =
                RenderTransaction(
                    finished.revision.takeIf { it >= 0 },
                    finished.operations.toList(),
                )
            renderer.applyDirectTransaction(directTransaction)
            val applyFinishedNs = SystemClock.elapsedRealtimeNanos()

            if (commitMeasurement != null) {
                Log.i(
                    MainActivity.TAG,
                    "VYNE_BENCH architecture=direct " +
                        "phase=${commitMeasurement.phase} " +
                        "bridge_ns=${bridgeFinishedNs - commitMeasurement.startedNs} " +
                        "apply_ns=${applyFinishedNs - applyStartedNs} " +
                        "total_ns=${applyFinishedNs - commitMeasurement.startedNs} " +
                        "operations=${directTransaction.logicalOperationCount}",
                )
            }
            onCommitApplied()
        }
    }

    private fun abortCommit() {
        transaction = null
        measurement = null
    }

    private fun add(operation: RenderOperation) {
        requireNotNull(transaction) { "No direct commit is active" }
            .operations
            .add(operation)
    }

    private fun decodeOperation(op: JSONObject): RenderOperation =
        when (op.getString("op")) {
            "clear" -> RenderOperation.Clear(op.getInt("id"))
            "create" -> RenderOperation.Create(op.getInt("id"), op.getString("kind"))
            "set_props" ->
                RenderOperation.SetProps(
                    op.getInt("id"),
                    decodeProps(op.getJSONObject("props")),
                )
            "set_prop" ->
                RenderOperation.SetProp(
                    op.getInt("id"),
                    op.getString("name"),
                    decodeValue(op.get("value")),
                )
            "remove_prop" -> RenderOperation.RemoveProp(op.getInt("id"), op.getString("name"))
            "listen" ->
                RenderOperation.Listen(
                    op.getInt("id"),
                    op.getString("event"),
                    op.getInt("handler"),
                    "all",
                )
            "listen_latest" ->
                RenderOperation.Listen(
                    op.getInt("id"),
                    op.getString("event"),
                    op.getInt("handler"),
                    "latest",
                )
            "unlisten" -> RenderOperation.Unlisten(op.getInt("id"), op.getString("event"))
            "insert_child" ->
                RenderOperation.InsertChild(
                    op.getInt("parent"),
                    op.getInt("child"),
                    op.getInt("index"),
                )
            "move_child" ->
                RenderOperation.MoveChild(
                    op.getInt("parent"),
                    op.getInt("child"),
                    op.getInt("index"),
                )
            "remove_child" ->
                RenderOperation.RemoveChild(op.getInt("parent"), op.getInt("child"))
            "remove" -> RenderOperation.Remove(op.getInt("id"))
            "scroll_to" ->
                RenderOperation.ScrollTo(
                    op.getInt("id"),
                    op.getDouble("offset_x").toFloat(),
                    op.getDouble("offset_y").toFloat(),
                    op.getBoolean("animated"),
                )
            "motion_set_target" ->
                RenderOperation.MotionSetTarget(
                    animationId = op.getLong("animation_id"),
                    slotKey = op.getString("slot_key"),
                    nodeId = op.getInt("node_id"),
                    property = op.getString("property"),
                    targets = decodeTargets(op.getJSONArray("targets")),
                    slotId = if (op.isNull("slot_id")) null else op.getString("slot_id"),
                    specType = op.optString("spec_type", "tween"),
                    fromValue = decodeNullableFloat(op, "from_value"),
                    durationMs = op.optLong("duration_ms", 300),
                    easing = op.optString("easing", "ease_out"),
                    dampingRatio = op.optDouble("damping_ratio", 0.8).toFloat().coerceAtLeast(0.01f),
                    stiffness = op.optDouble("stiffness", 380.0).toFloat().coerceAtLeast(0.01f),
                    restValueThreshold = op.optDouble("rest_value_threshold", 0.01).toFloat(),
                    restVelocityThreshold = op.optDouble("rest_velocity_threshold", 0.01).toFloat(),
                    retargetPolicy = op.optString("retarget", "restart"),
                )
            "motion_cancel" ->
                RenderOperation.MotionCancel(
                    op.getLong("animation_id"),
                    op.getString("slot_key"),
                )
            "motion_driver_set_target" ->
                RenderOperation.MotionDriverSetTarget(
                    animationId = op.getLong("animation_id"),
                    driverId = op.getLong("driver_id"),
                    nodeId = op.getInt("node_id"),
                    property = op.getString("property"),
                    targets = decodeTargets(op.getJSONArray("targets")),
                    specType = op.optString("spec_type", "tween"),
                    fromValue = decodeNullableFloat(op, "from_value"),
                    durationMs = op.optLong("duration_ms", 300),
                    easing = op.optString("easing", "ease_out"),
                    dampingRatio = op.optDouble("damping_ratio", 0.8).toFloat().coerceAtLeast(0.01f),
                    stiffness = op.optDouble("stiffness", 380.0).toFloat().coerceAtLeast(0.01f),
                    restValueThreshold = op.optDouble("rest_value_threshold", 0.01).toFloat(),
                    restVelocityThreshold = op.optDouble("rest_velocity_threshold", 0.01).toFloat(),
                    retargetPolicy = op.optString("retarget", "restart"),
                )
            "motion_driver_cancel" ->
                RenderOperation.MotionDriverCancel(
                    op.getLong("animation_id"),
                    op.getLong("driver_id"),
                )
            else -> error("Unsupported direct operation: ${op.optString("op")}")
        }

    private fun decodeProps(props: JSONObject): Map<String, Any?> {
        val result = LinkedHashMap<String, Any?>(props.length())
        val keys = props.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            result[key] = decodeValue(props.get(key))
        }
        return result
    }

    private fun decodeTargets(targets: JSONArray): List<Float> =
        List(targets.length()) { index -> targets.getDouble(index).toFloat() }

    private fun decodeNullableFloat(op: JSONObject, name: String): Float? =
        if (op.isNull(name)) null else op.getDouble(name).toFloat()

    /**
     * Decode one JSON prop value to the Kotlin type the renderer already
     * expects: null, Boolean, Long, Double, String, or the org.json
     * containers for nested values (matching the previous bridge decode).
     */
    private fun decodeValue(value: Any?): Any? =
        when (value) {
            JSONObject.NULL -> null
            is Boolean -> value
            is Int -> value.toLong()
            is Long -> value
            is Double -> value
            is Float -> value.toDouble()
            is java.math.BigDecimal -> value.toDouble()
            is java.math.BigInteger ->
                error("Direct commit integer exceeds signed 64-bit range")
            else -> value
        }
}
