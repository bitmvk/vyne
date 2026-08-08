/**
 * Process-scoped owner of the single live MainActivity / Python runtime.
 *
 * This replaces Activity-instance state (`pythonRunning`, `launchSequence`)
 * as the authority for cold-vs-warm entry classification:
 * - COLD = the entry that starts a runtime session (no live owner).
 * - WARM = every entry delivered to a live owner.
 *
 * The singleton is lifecycle mechanics only — Python owns routing, batching,
 * and failure handling (agent.md).
 */
package dev.vyne

import java.lang.ref.WeakReference
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

internal object RuntimeOwner {
    private val liveOwner = AtomicReference<WeakReference<MainActivity>?>()
    private val sequence = AtomicLong(0L)

    /**
     * Atomically claim ownership. Returns the existing live owner to
     * forward to, or null when this activity becomes the owner (cold start).
     *
     * Winning ownership starts a new runtime session: the entry sequence
     * resets so the first launch of the session is sequence 1 (per-session
     * monotonic, matching the previous per-Activity behavior).
     */
    fun claim(activity: MainActivity): MainActivity? = synchronized(this) {
        val ref = liveOwner.get()
        val owner = ref?.get()
        if (owner == null || owner.isFinishing || owner.isDestroyed) {
            // Winning ownership starts a NEW session: the sequence resets
            // so the first entry of the session is 1 (= COLD). Only the
            // current owner may clear live state; a stale release from the
            // replaced activity cannot touch the new session.
            liveOwner.set(WeakReference(activity))
            sequence.set(0L)
            null
        } else {
            owner
        }
    }

    /** Release ownership when the owner activity is destroyed. */
    fun release(activity: MainActivity) = synchronized(this) {
        if (liveOwner.get()?.get() === activity) {
            liveOwner.set(null)
        }
    }

    /** Monotonic entry sequence across Activity instances within a session. */
    fun nextSequence(): Long = sequence.incrementAndGet()

    /** Mark the process running — only the current owner may do so. */
}
