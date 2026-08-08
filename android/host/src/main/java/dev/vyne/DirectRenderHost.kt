package dev.vyne

import android.content.Context
import android.os.SystemClock
import android.util.Log
import com.chaquo.python.PyObject
import org.json.JSONTokener

/**
 * Small direct-call surface exposed to Python through Chaquopy.
 *
 * Calls arrive on the dedicated Python executor and only build an immutable
 * transaction. finishCommit posts one transaction to the Android UI thread.
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

    private data class ValueCursor(
        var longIndex: Int = 0,
        var doubleIndex: Int = 0,
        var stringIndex: Int = 0,
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
    fun extensionKinds(): Map<String, List<List<Any>>> =
        renderer.registryAccessor.extensionKinds().mapValues { (_, info) ->
            listOf(info.props.toList(), info.events.toList(), listOf(info.container))
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

    fun beginCommit(revision: Long) {
        check(transaction == null) { "A direct commit is already active" }
        transaction = Transaction(revision)
    }

    fun clear(id: Int) {
        add(RenderOperation.Clear(id))
    }

    fun create(id: Int, kind: String) {
        add(RenderOperation.Create(id, kind))
    }

    fun setProps(
        id: Int,
        names: Array<String>,
        tags: ByteArray,
        longValues: LongArray,
        doubleValues: DoubleArray,
        stringValues: Array<String>,
    ) {
        add(
            RenderOperation.SetProps(
                id,
                decodeValues(
                    names,
                    tags,
                    longValues,
                    doubleValues,
                    stringValues,
                ),
            ),
        )
    }

    fun setProp(
        id: Int,
        names: Array<String>,
        tags: ByteArray,
        longValues: LongArray,
        doubleValues: DoubleArray,
        stringValues: Array<String>,
    ) {
        require(names.size == 1) { "setProp requires exactly one property" }
        val props = decodeValues(
            names,
            tags,
            longValues,
            doubleValues,
            stringValues,
        )
        add(RenderOperation.SetProp(id, names[0], props[names[0]]))
    }

    fun setPropBatch(
        ids: IntArray,
        names: Array<String>,
        tags: ByteArray,
        longValues: LongArray,
        doubleValues: DoubleArray,
        stringValues: Array<String>,
    ) {
        require(ids.size == names.size) {
            "Direct property batch has different id and value lengths"
        }
        validateValueColumns(
            names.size,
            tags,
            longValues,
            doubleValues,
            stringValues,
        )
        val cursor = ValueCursor()
        val values =
            List(ids.size) { index ->
                decodeValue(
                    index,
                    cursor,
                    tags,
                    longValues,
                    doubleValues,
                    stringValues,
                )
            }
        add(
            RenderOperation.SetPropBatch(
                ids,
                names,
                values,
            ),
        )
    }

    fun commitPropBatch(
        revision: Long,
        ids: IntArray,
        names: Array<String>,
        tags: ByteArray,
        longValues: LongArray,
        doubleValues: DoubleArray,
        stringValues: Array<String>,
    ) {
        beginCommit(revision)
        try {
            setPropBatch(
                ids,
                names,
                tags,
                longValues,
                doubleValues,
                stringValues,
            )
            finishCommit()
        } catch (error: Throwable) {
            abortCommit()
            throw error
        }
    }

    fun setStringPropBatch(
        ids: IntArray,
        name: String,
        values: Array<String>,
    ) {
        require(ids.size == values.size) {
            "Direct string property batch has different id and value lengths"
        }
        add(
            RenderOperation.SetStringPropBatch(
                ids,
                name,
                values,
            ),
        )
    }

    fun commitStringPropBatch(
        revision: Long,
        ids: IntArray,
        name: String,
        values: Array<String>,
    ) {
        beginCommit(revision)
        try {
            setStringPropBatch(ids, name, values)
            finishCommit()
        } catch (error: Throwable) {
            abortCommit()
            throw error
        }
    }

    fun setContiguousStringPropBatch(
        firstId: Int,
        name: String,
        values: Array<String>,
    ) {
        require(values.size <= Int.MAX_VALUE - firstId) {
            "Direct contiguous property ids overflow Int"
        }
        add(
            RenderOperation.SetContiguousStringPropBatch(
                firstId,
                name,
                values,
            ),
        )
    }

    fun commitContiguousStringPropBatch(
        revision: Long,
        firstId: Int,
        name: String,
        values: Array<String>,
    ) {
        beginCommit(revision)
        try {
            setContiguousStringPropBatch(firstId, name, values)
            finishCommit()
        } catch (error: Throwable) {
            abortCommit()
            throw error
        }
    }

    fun mountNodes(
        ids: IntArray,
        kinds: Array<String>,
        propCounts: IntArray,
        names: Array<String>,
        tags: ByteArray,
        longValues: LongArray,
        doubleValues: DoubleArray,
        stringValues: Array<String>,
        parentIds: IntArray,
        insertionModes: ByteArray,
        insertionIndices: IntArray,
    ) {
        val nodeCount = ids.size
        require(
            kinds.size == nodeCount &&
                propCounts.size == nodeCount &&
                parentIds.size == nodeCount &&
                insertionModes.size == nodeCount &&
                insertionIndices.size == nodeCount
        ) {
            "Direct mount columns have different node lengths"
        }
        require(propCounts.all { it >= 0 } && propCounts.sum() == names.size) {
            "Direct mount property counts do not match property columns"
        }
        validateValueColumns(
            names.size,
            tags,
            longValues,
            doubleValues,
            stringValues,
        )

        var propertyIndex = 0
        val cursor = ValueCursor()
        for (nodeIndex in ids.indices) {
            val id = ids[nodeIndex]
            add(RenderOperation.Create(id, kinds[nodeIndex]))

            val propertyCount = propCounts[nodeIndex]
            if (propertyCount > 0) {
                val props = LinkedHashMap<String, Any?>(propertyCount)
                repeat(propertyCount) {
                    props[names[propertyIndex]] =
                        decodeValue(
                            propertyIndex,
                            cursor,
                            tags,
                            longValues,
                            doubleValues,
                            stringValues,
                        )
                    propertyIndex += 1
                }
                add(RenderOperation.SetProps(id, props))
            }

            when (insertionModes[nodeIndex].toInt()) {
                INSERT_NONE -> Unit
                INSERT_AT_INDEX ->
                    insertChild(
                        parentIds[nodeIndex],
                        id,
                        insertionIndices[nodeIndex],
                    )
                else ->
                    error(
                        "Unknown direct insertion mode " +
                            insertionModes[nodeIndex],
                    )
            }
        }
    }

    fun commitMountNodes(
        revision: Long,
        ids: IntArray,
        kinds: Array<String>,
        propCounts: IntArray,
        names: Array<String>,
        tags: ByteArray,
        longValues: LongArray,
        doubleValues: DoubleArray,
        stringValues: Array<String>,
        parentIds: IntArray,
        insertionModes: ByteArray,
        insertionIndices: IntArray,
        postParentIds: IntArray,
        postChildIds: IntArray,
        postInsertionIndices: IntArray,
        listenerIds: IntArray,
        listenerEvents: Array<String>,
        listenerHandlers: IntArray,
        listenerLatest: ByteArray,
    ) {
        require(
            postParentIds.size == postChildIds.size &&
                postParentIds.size == postInsertionIndices.size
        ) {
            "Direct post-mount insertion columns have different lengths"
        }
        require(
            listenerIds.size == listenerEvents.size &&
                listenerIds.size == listenerHandlers.size &&
                listenerIds.size == listenerLatest.size
        ) {
            "Direct mount listener columns have different lengths"
        }

        beginCommit(revision)
        try {
            mountNodes(
                ids,
                kinds,
                propCounts,
                names,
                tags,
                longValues,
                doubleValues,
                stringValues,
                parentIds,
                insertionModes,
                insertionIndices,
            )
            for (index in postParentIds.indices) {
                insertChild(
                    postParentIds[index],
                    postChildIds[index],
                    postInsertionIndices[index],
                )
            }
            for (index in listenerIds.indices) {
                listen(
                    listenerIds[index],
                    listenerEvents[index],
                    listenerHandlers[index],
                    listenerLatest[index].toInt() != 0,
                )
            }
            finishCommit()
        } catch (error: Throwable) {
            abortCommit()
            throw error
        }
    }

    fun removeProp(id: Int, name: String) {
        add(RenderOperation.RemoveProp(id, name))
    }

    fun listen(id: Int, event: String, handler: Int, latest: Boolean) {
        add(
            RenderOperation.Listen(
                id,
                event,
                handler,
                if (latest) "latest" else "all",
            ),
        )
    }

    fun unlisten(id: Int, event: String) {
        add(RenderOperation.Unlisten(id, event))
    }

    fun insertChild(parent: Int, child: Int, index: Int) {
        add(RenderOperation.InsertChild(parent, child, index))
    }

    fun moveChild(parent: Int, child: Int, index: Int) {
        add(RenderOperation.MoveChild(parent, child, index))
    }

    fun removeChild(parent: Int, child: Int) {
        add(RenderOperation.RemoveChild(parent, child))
    }

    fun remove(id: Int) {
        add(RenderOperation.Remove(id))
    }

    fun scrollTo(id: Int, offsetX: Float, offsetY: Float, animated: Boolean) {
        add(RenderOperation.ScrollTo(id, offsetX, offsetY, animated))
    }

    fun motionSetTarget(
        animationId: Long,
        slotKey: String,
        nodeId: Int,
        property: String,
        targets: DoubleArray,
        slotId: String?,
        specType: String,
        fromValue: Float?,
        durationMs: Long,
        easing: String,
        dampingRatio: Float,
        stiffness: Float,
        restValueThreshold: Float,
        restVelocityThreshold: Float,
        retargetPolicy: String,
    ) {
        add(
            RenderOperation.MotionSetTarget(
                animationId,
                slotKey,
                nodeId,
                property,
                targets.map { it.toFloat() },
                slotId,
                specType,
                fromValue,
                durationMs,
                easing,
                dampingRatio.coerceAtLeast(0.01f),
                stiffness.coerceAtLeast(0.01f),
                restValueThreshold,
                restVelocityThreshold,
                retargetPolicy,
            ),
        )
    }

    fun motionCancel(animationId: Long, slotKey: String) {
        add(RenderOperation.MotionCancel(animationId, slotKey))
    }

    fun motionDriverSetTarget(
        animationId: Long,
        driverId: Long,
        nodeId: Int,
        property: String,
        targets: DoubleArray,
        specType: String,
        fromValue: Float?,
        durationMs: Long,
        easing: String,
        dampingRatio: Float,
        stiffness: Float,
        restValueThreshold: Float,
        restVelocityThreshold: Float,
        retargetPolicy: String,
    ) {
        add(
            RenderOperation.MotionDriverSetTarget(
                animationId = animationId,
                driverId = driverId,
                nodeId = nodeId,
                property = property,
                targets = targets.map { it.toFloat() },
                specType = specType,
                fromValue = fromValue,
                durationMs = durationMs,
                easing = easing,
                dampingRatio = dampingRatio.coerceAtLeast(0.01f),
                stiffness = stiffness.coerceAtLeast(0.01f),
                restValueThreshold = restValueThreshold,
                restVelocityThreshold = restVelocityThreshold,
                retargetPolicy = retargetPolicy,
            ),
        )
    }

    fun motionDriverCancel(animationId: Long, driverId: Long) {
        add(RenderOperation.MotionDriverCancel(animationId, driverId))
    }

    fun finishCommit() {
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

    fun abortCommit() {
        transaction = null
        measurement = null
    }

    private fun add(operation: RenderOperation) {
        requireNotNull(transaction) { "No direct commit is active" }
            .operations
            .add(operation)
    }

    private fun decodeValues(
        names: Array<String>,
        tags: ByteArray,
        longValues: LongArray,
        doubleValues: DoubleArray,
        stringValues: Array<String>,
    ): Map<String, Any?> {
        val size = names.size
        validateValueColumns(
            size,
            tags,
            longValues,
            doubleValues,
            stringValues,
        )

        val result = LinkedHashMap<String, Any?>(size)
        val cursor = ValueCursor()
        for (index in names.indices) {
            result[names[index]] =
                decodeValue(
                    index,
                    cursor,
                    tags,
                    longValues,
                    doubleValues,
                    stringValues,
                )
        }
        return result
    }

    private fun validateValueColumns(
        size: Int,
        tags: ByteArray,
        longValues: LongArray,
        doubleValues: DoubleArray,
        stringValues: Array<String>,
    ) {
        val longCount =
            tags.count {
                it.toInt() == VALUE_BOOL || it.toInt() == VALUE_INT
            }
        val doubleCount = tags.count { it.toInt() == VALUE_FLOAT }
        val stringCount =
            tags.count {
                it.toInt() == VALUE_STRING || it.toInt() == VALUE_JSON
            }
        require(
            tags.size == size &&
                longValues.size == longCount &&
                doubleValues.size == doubleCount &&
                stringValues.size == stringCount
        ) {
            "Direct property columns have different lengths"
        }
    }

    private fun decodeValue(
        index: Int,
        cursor: ValueCursor,
        tags: ByteArray,
        longValues: LongArray,
        doubleValues: DoubleArray,
        stringValues: Array<String>,
    ): Any? =
        when (tags[index].toInt()) {
            VALUE_NULL -> null
            VALUE_BOOL -> {
                val value = longValues[cursor.longIndex] != 0L
                cursor.longIndex += 1
                value
            }
            VALUE_INT -> {
                val value = longValues[cursor.longIndex]
                cursor.longIndex += 1
                value
            }
            VALUE_FLOAT -> {
                val value = doubleValues[cursor.doubleIndex]
                cursor.doubleIndex += 1
                value
            }
            VALUE_STRING -> {
                val value = stringValues[cursor.stringIndex]
                cursor.stringIndex += 1
                value
            }
            VALUE_JSON -> {
                val value =
                    JSONTokener(
                        stringValues[cursor.stringIndex],
                    ).nextValue()
                cursor.stringIndex += 1
                value
            }
            else -> error("Unknown direct value tag ${tags[index]}")
        }

    private companion object {
        const val VALUE_NULL = 0
        const val VALUE_BOOL = 1
        const val VALUE_INT = 2
        const val VALUE_FLOAT = 3
        const val VALUE_STRING = 4
        const val VALUE_JSON = 5
        const val INSERT_NONE = 0
        const val INSERT_AT_INDEX = 1
    }
}
