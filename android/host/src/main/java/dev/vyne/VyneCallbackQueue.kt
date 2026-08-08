package dev.vyne

import com.chaquo.python.PyObject
import java.lang.ref.WeakReference
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

/**
 * Ordered external-callback machinery shared by every render host.
 *
 * MainActivity and every RenderSurface own one queue each. The queue wraps
 * Python callables in thread-safe VyneCallbacks, applies the mechanical
 * admission policy (all/latest, sampling), and hands call/dispose tasks to
 * the host's BridgeWorkScheduler for ordered dispatch into Python.
 *
 * The queue deliberately avoids retaining the host: invocations arrive from
 * arbitrary Android threads, so the host is referenced weakly and the
 * aliveness check is supplied by the host at construction.
 */
class VyneCallbackQueue(
    private val uiPost: (Runnable) -> Unit,
    private val isAlive: () -> Boolean,
    private val bridge: CallbackBridge,
) {
    /** The host-side ordered work queue surface the queue needs. */
    interface CallbackBridge {
        fun enqueueCallback(task: CallbackTask, latestKey: Long?)

        fun removeCallbacks(predicate: (CallbackTask) -> Boolean)

        fun flushPending()
    }

    /** One typed task crossing from the host owner queue into Python. */
    sealed interface CallbackTask {
        data class Call(
            val owner: ScheduledVyneCallback,
            val payload: Any?,
        ) : CallbackTask

        data class Dispose(
            val callbackId: Long,
            val callback: PyObject,
        ) : CallbackTask
    }

    /**
     * Avoid retaining a destroyed host when application-owned Android work
     * keeps a callback beyond the host lifecycle.
     */
    class ScheduledVyneCallback internal constructor(
        queue: VyneCallbackQueue,
        val callbackId: Long,
        callback: PyObject,
        private val admission: CallbackAdmission,
    ) : VyneCallback {
        private val queue = WeakReference(queue)
        private val active = AtomicBoolean(true)
        private val callback = AtomicReference<PyObject?>(callback)
        val delivery: String
            get() = admission.delivery

        override fun invoke(payload: Any?) {
            if (!active.get() || !admission.accept()) return
            queue.get()?.scheduleCall(this, payload)
        }

        override fun dispose() {
            if (!active.compareAndSet(true, false)) return
            val released = callback.getAndSet(null) ?: return
            queue.get()?.scheduleDisposal(callbackId, released)
        }

        fun callbackIfActive(): PyObject? =
            if (active.get()) callback.get() else null

        fun deactivateForShutdown() {
            active.set(false)
            callback.set(null)
        }
    }

    private val activeCallbacks = ConcurrentHashMap<Long, ScheduledVyneCallback>()
    private val nextCallbackId = AtomicLong(1L)

    fun createCallback(
        callback: PyObject,
        delivery: String,
        sampleIntervalMs: Long,
    ): VyneCallback {
        val callbackId = nextCallbackId.getAndIncrement()
        val scheduled =
            ScheduledVyneCallback(
                this,
                callbackId,
                callback,
                CallbackAdmission(delivery, sampleIntervalMs),
            )
        activeCallbacks[callbackId] = scheduled
        return scheduled
    }

    fun deactivateAll() {
        activeCallbacks.values.forEach(ScheduledVyneCallback::deactivateForShutdown)
        activeCallbacks.clear()
    }

    /**
     * Enter through the UI thread before touching bridge queue state. The
     * callback itself is later admitted through the host's Python executor
     * and invoked by the single-owner asyncio runtime.
     */
    private fun scheduleCall(owner: ScheduledVyneCallback, payload: Any?) {
        uiPost {
            if (!isAlive()) return@uiPost
            if (owner.callbackIfActive() == null) return@uiPost
            bridge.enqueueCallback(
                CallbackTask.Call(owner, payload),
                latestKey =
                    if (owner.delivery == "latest") owner.callbackId else null,
            )
            bridge.flushPending()
        }
    }

    private fun scheduleDisposal(callbackId: Long, callback: PyObject) {
        activeCallbacks.remove(callbackId)
        uiPost {
            if (!isAlive()) return@uiPost
            bridge.removeCallbacks { task ->
                task is CallbackTask.Call &&
                    task.owner.callbackId == callbackId
            }
            bridge.enqueueCallback(CallbackTask.Dispose(callbackId, callback), null)
            bridge.flushPending()
        }
    }
}
