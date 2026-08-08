package dev.vyne

import android.os.SystemClock
import com.chaquo.python.PyObject
import java.util.concurrent.atomic.AtomicLong

/**
 * A thread-safe entry point from application-owned Android code into Python.
 *
 * Invocations and disposal are serialized by MainActivity onto Vyne's single
 * Python executor, so either method may be called from any Android thread.
 */
interface VyneCallback {
    fun invoke(payload: Any?)

    fun dispose()
}

/** One typed task crossing from the Android owner queue into Python. */
internal data class ExternalPythonTask(
    val kind: String,
    val callback: PyObject,
    val payload: Any?,
)

/** Thread-safe mechanical admission policy selected by the Python API. */
internal class CallbackAdmission(
    val delivery: String,
    private val sampleIntervalMs: Long,
    private val clockMs: () -> Long = SystemClock::elapsedRealtime,
) {
    private val lastAcceptedAtMs = AtomicLong(Long.MIN_VALUE)

    init {
        require(delivery == "all" || delivery == "latest") {
            "Callback delivery must be all or latest"
        }
        require(sampleIntervalMs >= 0L) {
            "Callback sample interval must be non-negative"
        }
    }

    fun accept(): Boolean {
        if (sampleIntervalMs == 0L) return true
        val now = clockMs()
        while (true) {
            val previous = lastAcceptedAtMs.get()
            if (
                previous != Long.MIN_VALUE &&
                    now - previous < sampleIntervalMs
            ) {
                return false
            }
            if (lastAcceptedAtMs.compareAndSet(previous, now)) return true
        }
    }
}
