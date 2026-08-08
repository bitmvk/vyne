package dev.vyne

/**
 * Serializes all work entering Python through one explicit backpressure gate.
 *
 * Receipts, launches, user events, and application callbacks keep their
 * distinct ordering rules, while MainActivity is limited to executing the
 * scheduler's next decision.
 */
internal class BridgeWorkScheduler<C> {
    data class LatestKey(
        val target: Int,
        val name: String,
        val handler: Int,
        val gestureId: Any?,
    )

    sealed interface Work<out C> {
        data class Events(val values: List<NativeEvent>) : Work<Nothing>
        data class Launch(val value: NativeLaunchData) : Work<Nothing>
        data class Data(val value: Any?) : Work<Nothing>
        data class Callbacks<C>(val values: List<C>) : Work<C>
    }

    private data class QueuedCallback<C>(val value: C, val latestKey: Long?)

    private val events = ArrayDeque<NativeEvent>()
    private val receipts = ArrayDeque<NativeEvent>()
    private val launches = ArrayDeque<NativeLaunchData>()
    private val data = ArrayDeque<Any?>()
    private val callbacks = ArrayDeque<QueuedCallback<C>>()
    private val latestEventSlots = mutableMapOf<LatestKey, Int>()
    private val latestCallbackSlots = mutableMapOf<Long, Int>()

    var inFlight: Boolean = false
        private set

    val hasPendingWork: Boolean
        get() =
            receipts.isNotEmpty() ||
                events.isNotEmpty() ||
                launches.isNotEmpty() ||
                data.isNotEmpty() ||
                callbacks.isNotEmpty()

    fun beginStartup() {
        check(!inFlight) { "Python dispatch is already in flight" }
        inFlight = true
    }

    fun enqueueEvent(event: NativeEvent) {
        enqueuePendingEvent(events, latestEventSlots, event)
    }

    fun enqueueReceipt(event: NativeEvent) {
        receipts.add(event)
    }

    fun enqueueLaunch(launch: NativeLaunchData) {
        launches.add(launch)
    }

    /** Surface-only: a warm data delivery (RenderSurface has no intents). */
    fun enqueueData(value: Any?) {
        data.add(value)
    }

    fun enqueueCallback(value: C, latestKey: Long? = null) {
        val queued = QueuedCallback(value, latestKey)
        if (latestKey == null) {
            callbacks.add(queued)
        } else {
            enqueueLatestWork(callbacks, latestCallbackSlots, latestKey, queued)
        }
    }

    fun removeCallbacks(predicate: (C) -> Boolean) {
        callbacks.removeAll { predicate(it.value) }
        rebuildLatestCallbackSlots()
    }

    fun next(): Work<C>? {
        if (inFlight || !hasPendingWork) return null

        val work: Work<C> =
            if (launches.isNotEmpty()) {
                if (receipts.isNotEmpty()) {
                    Work.Events(receipts.toList().also { receipts.clear() })
                } else {
                    Work.Launch(launches.removeFirst())
                }
            } else if (data.isNotEmpty()) {
                if (receipts.isNotEmpty()) {
                    Work.Events(receipts.toList().also { receipts.clear() })
                } else {
                    Work.Data(data.removeFirst())
                }
            } else {
                val pendingEvents = receipts.toList() + events.toList()
                receipts.clear()
                clearEventQueue(events, latestEventSlots)
                if (pendingEvents.isNotEmpty()) {
                    Work.Events(pendingEvents)
                } else {
                    Work.Callbacks(callbacks.map { it.value }.also {
                        callbacks.clear()
                        latestCallbackSlots.clear()
                    })
                }
            }

        inFlight = true
        return work
    }

    fun finish() {
        inFlight = false
    }

    fun clear() {
        clearEventQueue(events, latestEventSlots)
        receipts.clear()
        launches.clear()
        data.clear()
        callbacks.clear()
        latestCallbackSlots.clear()
        inFlight = false
    }

    private fun rebuildLatestCallbackSlots() {
        latestCallbackSlots.clear()
        callbacks.forEachIndexed { index, queued ->
            queued.latestKey?.let { latestCallbackSlots[it] = index }
        }
    }

    companion object {
        fun enqueuePendingEvent(
            queue: ArrayDeque<NativeEvent>,
            latestSlots: MutableMap<LatestKey, Int>,
            event: NativeEvent,
        ) {
            val isReceipt =
                event.name == "__vyne_system__" &&
                    event.payload["type"] == "native_apply_result"
            if (event.delivery == "latest" && !isReceipt) {
                val key =
                    LatestKey(
                        target = event.target,
                        name = event.name,
                        handler = event.handler,
                        gestureId = event.payload["gesture_id"],
                    )
                replaceLatest(queue, latestSlots, key, event)
                return
            }
            queue.add(event)
        }

        fun clearEventQueue(
            queue: ArrayDeque<NativeEvent>,
            latestSlots: MutableMap<LatestKey, Int>,
        ) {
            queue.clear()
            latestSlots.clear()
        }

        fun <K, T> enqueueLatestWork(
            queue: ArrayDeque<T>,
            latestSlots: MutableMap<K, Int>,
            key: K,
            value: T,
        ) {
            replaceLatest(queue, latestSlots, key, value)
        }

        private fun <K, T> replaceLatest(
            queue: ArrayDeque<T>,
            latestSlots: MutableMap<K, Int>,
            key: K,
            value: T,
        ) {
            val existingIndex = latestSlots.remove(key)
            if (existingIndex != null) {
                queue.removeAt(existingIndex)
                for (slot in latestSlots.entries) {
                    if (slot.value > existingIndex) slot.setValue(slot.value - 1)
                }
            }
            latestSlots[key] = queue.size
            queue.add(value)
        }
    }
}
