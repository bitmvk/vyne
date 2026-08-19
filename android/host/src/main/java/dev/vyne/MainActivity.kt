/**
 * The single Activity that hosts a Vyne application.
 *
 * Architecture:
 * - Chaquopy bridge calls run on a dedicated executor (not the UI thread).
 * - Runtime work and async callback continuations share one Python asyncio owner thread.
 * - The Renderer runs on the UI thread (it touches Views).
 * - Events flow: Android widget → Renderer.eventSink → BridgeWorkScheduler → dispatch when
 * Python is idle → commit back → runOnUiThread → Renderer transaction application.
 *
 * Backpressure: At most one Python dispatch is in flight. Events that arrive while Python is busy
 * remain queued; `latest` listeners coalesce by gesture key, while launches and application
 * callbacks use the same single-owner boundary. As soon as the active dispatch completes, queued
 * work is dispatched without waiting for a display-frame boundary.
 */
package dev.vyne

import android.content.res.Configuration
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.view.MotionEvent
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

open class MainActivity : ComponentActivity(), VyneCallbackQueue.CallbackBridge {
    companion object {
        const val TAG = "Vyne"
    }

    private val pythonExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private val bridgeWork = BridgeWorkScheduler<VyneCallbackQueue.CallbackTask>()
    private lateinit var callbackQueue: VyneCallbackQueue
    private lateinit var pythonModule: PyObject
    private lateinit var renderer: Renderer
    private lateinit var directHost: DirectRenderHost
    @Volatile private var pythonRunning = false


    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Cold-vs-warm: if another instance owns the live runtime, forward
        // this entry there and never start a second Python owner.
        val existing = RuntimeOwner.claim(this)
        if (existing != null && !existing.isFinishing && !existing.isDestroyed) {
            existing.forwardEntry(intent)
            finish()
            return
        }

        // Process-once registration: core widgets + extensions (generated
        // registrant) + surface declarations, frozen before any Python
        // starts. Any entry point (activity, receiver, service) can trigger
        // it; side effects run exactly once per process.
        val registry = AppBootstrap.ensureRegistered(this)

        callbackQueue =
            VyneCallbackQueue(
                uiPost = { runOnUiThread(it) },
                isAlive = { !isFinishing && !isDestroyed },
                bridge = this,
            )

        renderer =
                Renderer(
                        this,
                        eventSink = { event -> scheduleEventToPython(event) },
                        applyResultSink = { result, revision ->
                            if (pythonRunning && revision != null) {
                                scheduleApplyResultToPython(result, revision)
                            }
                        },
                        registry = registry,
                )
        directHost =
                DirectRenderHost(
                        uiPost = { runOnUiThread(it) },
                        isAlive = { !isFinishing && !isDestroyed },
                        renderer = renderer,
                        onCommitApplied = ::finishEventDispatch,
                        callbackFactory = callbackQueue::createCallback,
                        contextProvider = { this },
                )

        setContentView(renderer.root)
        bridgeWork.beginStartup()
        startPython(nextLaunch(intent))

        // The host asks Python on every system back press. Python consumes
        // the press when any registered back handler returns true; the
        // default (finish) is used when Python is down, busy past the
        // timeout, or uninterested.
        onBackPressedDispatcher.addCallback(
                this,
                object : OnBackPressedCallback(true) {
                    override fun handleOnBackPressed() {
                        if (!pythonConsumesBackPress()) finish()
                    }
                },
        )
    }

    /**
     * Synchronous request/response over the bridge: the UI thread waits on
     * the pythonExecutor result (bounded), never calls Chaquopy itself.
     * The runtime loop serializes the query with events, launches, and
     * receipts, so ordering holds at the single-owner boundary.
     */
    private fun pythonConsumesBackPress(): Boolean {
        if (!pythonRunning || !::pythonModule.isInitialized) return false
        return try {
            val result =
                    pythonExecutor.submit<Boolean> {
                        pythonModule.callAttr("back_press_query").toBoolean()
                    }
            if (result.get(250, TimeUnit.MILLISECONDS)) {
                true
            } else {
                false
            }
        } catch (error: Throwable) {
            Log.e(TAG, "Back-press query failed; defaulting to finish", error)
            false
        }
    }

    /**
     * Deliver an entry to this (live) owner: warm path, queued and ordered.
     * A second Activity instance can only forward after this Activity's
     * onCreate has returned (single UI thread), so bridgeWork.beginStartup()
     * has always run — every forwarded entry is enqueued immediately and
     * never collapsed, including while Python is still booting.
     */
    fun forwardEntry(intent: Intent) {
        scheduleLaunchToPython(nextLaunch(intent))
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        scheduleLaunchToPython(nextLaunch(intent))
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (::renderer.isInitialized) {
            // The Activity and Python runtime deliberately survive rotation.
            // Android has already updated Resources and the window bounds;
            // remeasure the native tree and redispatch system insets in place.
            renderer.root.requestLayout()
            renderer.root.requestApplyInsets()
        }
    }

    override fun onResume() {
        super.onResume()
        emitAppState("active")
    }

    override fun onPause() {
        super.onPause()
        emitAppState("inactive")
    }

    override fun onStop() {
        super.onStop()
        emitAppState("background")
    }

    /** Deliver the app lifecycle to Python as an ordered system event. */
    private fun emitAppState(state: String) {
        if (!::renderer.isInitialized || !::pythonModule.isInitialized) return
        scheduleEventToPython(
            NativeEvent(
                sequence = 0L,
                target = 0,
                name = "__vyne_system__",
                handler = 0,
                payload = mapOf("type" to "app_state", "state" to state),
                delivery = "ordered",
            )
        )
    }

    override fun onDestroy() {
        if (::callbackQueue.isInitialized) callbackQueue.deactivateAll()

        // Serialize Python shutdown after previously submitted work.
        if (::pythonModule.isInitialized) {
            try {
                pythonExecutor
                        .submit {
                            pythonModule.callAttr(
                                "shutdown_runtime",
                                directHost,
                            )
                        }
                        .get(10, TimeUnit.SECONDS)
            } catch (error: Throwable) {
                Log.e(TAG, "Python runtime shutdown failed", error)
            }
        }

        // Drain pending bridge work — it cannot be dispatched after shutdown.
        bridgeWork.clear()
        pythonRunning = false

        // Dispose the renderer (idempotent, safe after destroy).
        if (::renderer.isInitialized) renderer.dispose()
        RuntimeOwner.release(this)

        pythonExecutor.shutdown()
        if (!pythonExecutor.awaitTermination(10, TimeUnit.SECONDS)) {
            Log.e(TAG, "Python executor did not terminate after JNI shutdown")
            pythonExecutor.shutdownNow()
        }
        super.onDestroy()
    }

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        if (::renderer.isInitialized) renderer.handleTouchEvent(event)
        return super.dispatchTouchEvent(event)
    }

    /**
     * Start the Python runtime on the background executor.
     *
     * Initialization is async. Python publishes the first transaction directly
     * through DirectRenderHost.
     */
    private fun startPython(initialLaunch: NativeLaunchData) {
        pythonExecutor.execute {
            try {
                pythonRunning = true
                directHost.beginMeasurement("startup")
                pythonModule = Python.getInstance().getModule("vyne.android")
                pythonModule.callAttr(
                        "start_direct",
                        configuredModuleName(),
                        directHost,
                        initialLaunch.action,
                        initialLaunch.uri,
                        initialLaunch.extras,
                        initialLaunch.sequence,
                )
                if (!directHost.commitScheduled()) {
                    runOnUiThread(::finishEventDispatch)
                }
            } catch (error: Throwable) {
                Log.e(TAG, "Failed to start Python runtime", error)
                pythonRunning = false
                runOnUiThread {
                    showStartupError(error)
                    finishEventDispatch()
                }
            }
        }
    }

    /**
     * Dev-only hot reload hook (``vyne live push``): re-run the app's Python
     * by recreating this Activity. The process stays alive, so on recreate
     * ``start_direct`` re-imports the app module and ``vyne.live`` resolves
     * the pushed copies from the live tree. Called by the loader watcher
     * from a non-UI thread.
     */
    fun requestReload() {
        runOnUiThread {
            if (!isFinishing && !isDestroyed) recreate()
        }
    }

    /** Execute one launch selected by the activity's bridge-work queue. */
    private fun dispatchLaunchToPython(launch: NativeLaunchData) {
        pythonExecutor.execute {
            if (!pythonRunning || !::pythonModule.isInitialized) {
                runOnUiThread(::finishEventDispatch)
                return@execute
            }
            try {
                directHost.beginMeasurement("launch")
                pythonModule.callAttr(
                        "deliver_launch_direct",
                        launch.action,
                        launch.uri,
                        launch.extras,
                        launch.sequence,
                )
                if (!directHost.commitScheduled()) {
                    runOnUiThread(::finishEventDispatch)
                }
            } catch (error: Throwable) {
                Log.e(TAG, "Failed to deliver Android launch to Python", error)
                runOnUiThread(::finishEventDispatch)
            }
        }
    }

    private fun scheduleLaunchToPython(launch: NativeLaunchData) {
        bridgeWork.enqueueLaunch(launch)
        flushPendingEventsIfIdle()
    }

    // ---- VyneCallbackQueue.CallbackBridge ----

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

    private fun nextLaunch(intent: Intent): NativeLaunchData {
        // Origin is derived from the session sequence (1 = COLD, later =
        // WARM); the sequence is the only launch state that exists.
        return LaunchIntentAdapter.fromIntent(intent, RuntimeOwner.nextSequence())
    }

    @Suppress("DEPRECATION")
    private fun configuredModuleName(): String {
        val info = packageManager.getApplicationInfo(packageName, PackageManager.GET_META_DATA)
        return info.metaData?.getString("dev.vyne.MODULE_NAME") ?: "app"
    }

    private fun dispatchEventsToPython(events: List<NativeEvent>) {
        if (!pythonRunning) {
            // Python never started or has already crashed; nothing to
            // dispatch to. Drain all pending bridge work and return.
            bridgeWork.clear()
            return
        }
        pythonExecutor.execute {
            try {
                val phase =
                        if (events.all { it.name == "__vyne_system__" }) {
                            "receipt"
                        } else {
                            "event"
                        }
                directHost.beginMeasurement(phase)
                if (
                        events.size == 1 &&
                                events[0].name == "__vyne_system__" &&
                                events[0].payload["type"] == "native_apply_result"
                ) {
                    val payload = events[0].payload
                    pythonModule.callAttr(
                            "dispatch_apply_result_direct",
                            payload["result"].toString(),
                            (payload["revision"] as Number).toLong(),
                            payload["session"].toString(),
                    )
                } else if (events.size == 1) {
                    val event = events[0]
                    pythonModule.callAttr(
                            "dispatch_event_direct",
                            event.sequence,
                            event.target,
                            event.name,
                            event.handler,
                            event.payload,
                    )
                } else {
                    pythonModule.callAttr("dispatch_events_direct", events)
                }
                if (!directHost.commitScheduled()) {
                    runOnUiThread(::finishEventDispatch)
                }
            } catch (error: Throwable) {
                Log.e(TAG, "Failed to dispatch ${events.size} Python event(s)", error)
                pythonRunning = false
                // No app-commit identity is available here, so this terminal
                // bridge failure must not fabricate an apply receipt.
                runOnUiThread {
                    // Preserve the last accepted tree; this is not a startup
                    // fallback and has no correlated app revision.
                    finishEventDispatch()
                }
            }
        }
    }

    private fun dispatchPythonCallbacks(tasks: List<ExternalPythonTask>) {
        if (!pythonRunning) {
            bridgeWork.clear()
            return
        }
        pythonExecutor.execute {
            try {
                directHost.beginMeasurement("callback")
                pythonModule.callAttr("dispatch_external_callbacks_direct", tasks)
                if (!directHost.commitScheduled()) {
                    runOnUiThread(::finishEventDispatch)
                }
            } catch (error: Throwable) {
                Log.e(TAG, "Failed to dispatch external callbacks", error)
                pythonRunning = false
                runOnUiThread(::finishEventDispatch)
            }
        }
    }

    /** Queue an event and dispatch it immediately when Python is idle. */
    private fun scheduleEventToPython(event: NativeEvent) {
        bridgeWork.enqueueEvent(event)
        flushPendingEventsIfIdle()
    }

    private fun flushPendingEventsIfIdle() {
        if (isFinishing || isDestroyed) {
            bridgeWork.clear()
            return
        }

        when (val work = bridgeWork.next()) {
            null -> return
            is BridgeWorkScheduler.Work.Events ->
                    dispatchEventsToPython(work.values)
            is BridgeWorkScheduler.Work.Launch ->
                    dispatchLaunchToPython(work.value)
            is BridgeWorkScheduler.Work.Data ->
                    error("MainActivity has no surface data path")
            is BridgeWorkScheduler.Work.Callbacks -> {
                val tasks =
                    work.values.mapNotNull { task ->
                        when (task) {
                            is VyneCallbackQueue.CallbackTask.Call ->
                                    task.owner.callbackIfActive()?.let { callback ->
                                        ExternalPythonTask("call", callback, task.payload)
                                    }
                            is VyneCallbackQueue.CallbackTask.Dispose ->
                                    ExternalPythonTask("dispose", task.callback, null)
                        }
                    }
                if (tasks.isEmpty()) {
                    bridgeWork.finish()
                    flushPendingEventsIfIdle()
                } else {
                    dispatchPythonCallbacks(tasks)
                }
            }
        }
    }

    private fun finishEventDispatch() {
        bridgeWork.finish()
        if (isFinishing || isDestroyed) return
        flushPendingEventsIfIdle()
    }

    /**
     * Enqueue a special system event carrying the ApplyResult and revision so Python can
     * acknowledge the native state and trigger recovery if needed. Both OK and failure results are
     * reported — Python needs OK acknowledgements to advance from AWAITING_APPLY back to SYNCED.
     */
    private fun scheduleApplyResultToPython(result: Renderer.ApplyResult, revision: Long) {
        val payload =
                mutableMapOf<String, Any?>(
                        "type" to "native_apply_result",
                        "result" to result.name.lowercase(),
                        "revision" to revision,
                        "session" to directHost.sessionId(),
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

    private fun showStartupError(error: Throwable) {
        renderer.applyDirectTransaction(
                RenderTransaction(
                        revision = null,
                        operations =
                                listOf(
                                        RenderOperation.Clear(0),
                                        RenderOperation.Create(1, "Text"),
                                        RenderOperation.SetProps(
                                                1,
                                                mapOf(
                                                        "text" to
                                                                "Python startup failed: " +
                                                                        error.message,
                                                ),
                                        ),
                                        RenderOperation.InsertChild(0, 1, 0),
                                ),
                ),
        )
    }
}
