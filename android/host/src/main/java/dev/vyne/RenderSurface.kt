package dev.vyne

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * One independently driven Renderer instance outside the main Activity.
 *
 * A RenderSurface owns its own Python executor, bridge work queue, callback
 * queue, Renderer, and DirectRenderHost. It mounts a separate Python runtime
 * (a registered app module) whose commits render into ``root``; the consumer
 * attaches ``root`` to any window it owns (WindowManager overlay, second
 * Activity, fragment) — the surface itself never touches a window.
 *
 * Lifecycle:
 * - ``start(data)`` — first mount: starts the surface runtime with *data*
 *   as its launch payload. Idempotent: a later ``start`` delivers instead.
 * - ``deliver(data)`` — warm update: rebuilds the root context and re-renders.
 * - ``unmount()`` — stops the Python runtime; the Renderer and host stay
 *   alive so a future ``start`` can re-mount cheaply.
 * - ``dispose()`` — full teardown (runtime, executor, renderer, callbacks).
 *
 * All public methods are safe from any thread; Python bridge calls are
 * serialized on the surface's own single-thread executor, mirroring the
 * MainActivity model (one in-flight dispatch, ordered queue, receipts).
 */
class RenderSurface internal constructor(
    val name: String,
    private val moduleName: String,
    context: Context,
    registry: ElementRegistry,
) {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val uiPost: (Runnable) -> Unit = mainHandler::post

    internal val renderer: Renderer
    val root: android.view.ViewGroup
        get() = renderer.root

    internal val host: DirectRenderHost
    val sessionId: String
        get() = host.sessionId()

    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val bridgeWork = BridgeWorkScheduler<VyneCallbackQueue.CallbackTask>()
    private val callbackQueue =
        VyneCallbackQueue(
            uiPost = uiPost,
            isAlive = { !unmounted && !disposed },
            bridge =
                object : VyneCallbackQueue.CallbackBridge {
                    override fun enqueueCallback(
                        task: VyneCallbackQueue.CallbackTask,
                        latestKey: Long?,
                    ) {
                        bridgeWork.enqueueCallback(task, latestKey)
                    }

                    override fun removeCallbacks(
                        predicate: (VyneCallbackQueue.CallbackTask) -> Boolean,
                    ) {
                        bridgeWork.removeCallbacks(predicate)
                    }

                    override fun flushPending() {
                        flushPendingEventsIfIdle()
                    }
                },
        )

    @Volatile private var pythonModule: PyObject? = null
    private val startLock = Any()
    @Volatile private var started = false
    @Volatile private var unmounted = false
    @Volatile private var disposed = false

    val isDisposed: Boolean
        get() = disposed

    init {
        renderer =
            Renderer(
                context.applicationContext,
                eventSink = { event -> scheduleEventToPython(event) },
                applyResultSink = { result, revision ->
                    if (started && revision != null) {
                        scheduleApplyResultToPython(result, revision)
                    }
                },
                registry = registry,
            )
        host =
            DirectRenderHost(
                uiPost = uiPost,
                isAlive = { !disposed && !renderer.disposed },
                renderer = renderer,
                onCommitApplied = ::finishEventDispatch,
                callbackFactory = callbackQueue::createCallback,
                contextProvider = { context.applicationContext },
            )
    }

    /** Start the surface runtime, or deliver when already started. */
    fun start(data: Map<String, Any?> = emptyMap()) {
        synchronized(startLock) {
            if (disposed) return
            if (started) {
                deliver(data)
                return
            }
            started = true
            bridgeWork.beginStartup()
        }
        executor.execute {
            try {
                pythonModule = Python.getInstance().getModule("vyne.android")
                pythonModule!!.callAttr("start_surface", name, moduleName, host, data)
                if (!host.commitScheduled()) {
                    uiPost { finishEventDispatch() }
                }
            } catch (error: Throwable) {
                Log.e(TAG, "Failed to start surface '$name'", error)
                synchronized(startLock) { started = false }
                uiPost {
                    bridgeWork.clear()
                    bridgeWork.finish()
                }
            }
        }
    }

    /** Deliver a warm update to the surface runtime (re-renders the root). */
    fun deliver(data: Map<String, Any?>) {
        if (!started || disposed) return
        bridgeWork.enqueueData(data)
        flushPendingEventsIfIdle()
    }

    /**
     * Stop the surface Python runtime. The Renderer and window remain the
     * consumer's property; call ``dispose()`` for full teardown.
     */
    fun unmount() {
        synchronized(startLock) {
            if (!started || unmounted || disposed) return
            unmounted = true
        }
        val module = pythonModule
        executor.execute {
            try {
                module?.callAttr("unmount_surface", name, host)
            } catch (error: Throwable) {
                Log.e(TAG, "Failed to unmount surface '$name'", error)
            }
            uiPost {
                bridgeWork.clear()
                bridgeWork.finish()
            }
        }
    }

    /** Full teardown: runtime, executor, renderer, callbacks. Idempotent. */
    fun dispose() {
        synchronized(startLock) {
            if (disposed) return
            disposed = true
            unmounted = true
        }
        val module = pythonModule
        try {
            val teardown =
                executor.submit {
                    try {
                        module?.callAttr("unmount_surface", name, host)
                    } catch (error: Throwable) {
                        Log.e(TAG, "Failed to dispose surface '$name'", error)
                    }
                    callbackQueue.deactivateAll()
                    bridgeWork.clear()
                    uiPost { renderer.dispose() }
                }
            // The Python session must be gone before a re-created surface
            // may start under the same name; otherwise start_surface races
            // the old unmount on the shared session slot.
            teardown.get(5, TimeUnit.SECONDS)
        } catch (error: Throwable) {
            Log.e(TAG, "Surface '$name' teardown did not complete", error)
        } finally {
            executor.shutdown()
        }
    }

    // ---- bridge plumbing (mirrors the MainActivity single-owner model) ----

    private fun scheduleEventToPython(event: NativeEvent) {
        bridgeWork.enqueueEvent(event)
        flushPendingEventsIfIdle()
    }

    private fun scheduleApplyResultToPython(result: Renderer.ApplyResult, revision: Long) {
        val payload =
            mutableMapOf<String, Any?>(
                "type" to "native_apply_result",
                "result" to result.name.lowercase(),
                "revision" to revision,
                "session" to host.sessionId(),
            )
        val systemEvent =
            NativeEvent(
                sequence = 0L,
                target = 0,
                name = "__vyne_system__",
                handler = 0,
                payload = payload,
                delivery = "ordered",
            )
        bridgeWork.enqueueReceipt(systemEvent)
        flushPendingEventsIfIdle()
    }

    private fun flushPendingEventsIfIdle() {
        if (unmounted || disposed) {
            bridgeWork.clear()
            return
        }
        when (val work = bridgeWork.next()) {
            null -> return
            is BridgeWorkScheduler.Work.Events ->
                dispatchEventsToPython(work.values)
            is BridgeWorkScheduler.Work.Data ->
                dispatchDataToPython(work.value)
            is BridgeWorkScheduler.Work.Callbacks ->
                dispatchCallbacksToPython(work.values)
            is BridgeWorkScheduler.Work.Launch ->
                error("RenderSurface has no launch path")
        }
    }

    private fun dispatchEventsToPython(events: List<NativeEvent>) {
        val module = pythonModule ?: run {
            bridgeWork.clear()
            return
        }
        executor.execute {
            try {
                val phase =
                    if (events.all { it.name == "__vyne_system__" }) {
                        "receipt"
                    } else {
                        "event"
                    }
                host.beginMeasurement(phase)
                if (
                    events.size == 1 &&
                    events[0].name == "__vyne_system__" &&
                    events[0].payload["type"] == "native_apply_result"
                ) {
                    val payload = events[0].payload
                    module.callAttr(
                        "dispatch_apply_result_surface",
                        name,
                        payload["result"].toString(),
                        (payload["revision"] as Number).toLong(),
                        payload["session"].toString(),
                    )
                } else if (events.size == 1) {
                    val event = events[0]
                    module.callAttr(
                        "dispatch_event_surface",
                        name,
                        event.sequence,
                        event.target,
                        event.name,
                        event.handler,
                        event.payload,
                    )
                } else {
                    module.callAttr("dispatch_events_surface", name, events)
                }
                if (!host.commitScheduled()) {
                    uiPost { finishEventDispatch() }
                }
            } catch (error: Throwable) {
                Log.e(TAG, "Failed to dispatch ${events.size} surface event(s)", error)
                uiPost {
                    finishEventDispatch()
                }
            }
        }
    }

    private fun dispatchDataToPython(data: Any?) {
        val module = pythonModule ?: run {
            bridgeWork.clear()
            return
        }
        executor.execute {
            try {
                host.beginMeasurement("deliver")
                module.callAttr("deliver_surface_data", name, data)
                if (!host.commitScheduled()) {
                    uiPost { finishEventDispatch() }
                }
            } catch (error: Throwable) {
                Log.e(TAG, "Failed to deliver surface data", error)
                uiPost { finishEventDispatch() }
            }
        }
    }

    private fun dispatchCallbacksToPython(tasks: List<VyneCallbackQueue.CallbackTask>) {
        val module = pythonModule ?: run {
            bridgeWork.clear()
            return
        }
        val decoded =
            tasks.mapNotNull { task ->
                when (task) {
                    is VyneCallbackQueue.CallbackTask.Call ->
                        task.owner.callbackIfActive()?.let { callback ->
                            ExternalPythonTask("call", callback, task.payload)
                        }
                    is VyneCallbackQueue.CallbackTask.Dispose ->
                        ExternalPythonTask("dispose", task.callback, null)
                }
            }
        if (decoded.isEmpty()) {
            bridgeWork.finish()
            flushPendingEventsIfIdle()
            return
        }
        executor.execute {
            try {
                host.beginMeasurement("callback")
                module.callAttr("dispatch_external_callbacks_surface", name, decoded)
                if (!host.commitScheduled()) {
                    uiPost { finishEventDispatch() }
                }
            } catch (error: Throwable) {
                Log.e(TAG, "Failed to dispatch surface callbacks", error)
                uiPost { finishEventDispatch() }
            }
        }
    }

    private fun finishEventDispatch() {
        bridgeWork.finish()
        if (unmounted || disposed) return
        flushPendingEventsIfIdle()
    }

    private companion object {
        const val TAG = "Vyne"
    }
}
