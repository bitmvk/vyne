package dev.vyne

import android.util.Log

/**
 * Run every restoration action even when some fail. The FIRST failure is
 * rethrown after all actions have run; later failures are attached as
 * suppressed exceptions, so nothing is silently erased (design-pattern #3).
 */
internal fun restoreAll(actions: List<() -> Unit>) {
    var first: Throwable? = null
    for (action in actions) {
        try {
            action()
        } catch (t: Throwable) {
            if (first == null) {
                first = t
            } else {
                first.addSuppressed(t)
            }
        }
    }
    if (first != null) throw first
}

/**
 * Owns native transaction admission, mutation journalling, and rollback.
 *
 * Renderer supplies the mechanical operations, but it no longer owns the
 * transaction state machine. Undo callbacks are accepted only while applying;
 * rollback cannot accidentally append more journal entries.
 */
internal class RenderTransactionApplier(
    private val preflight: (List<RenderOperation>) -> Unit,
    private val digest: () -> String,
    private val applyOperation: (RenderOperation) -> Unit,
) {
    private enum class Phase {
        IDLE,
        APPLYING,
        ROLLING_BACK,
    }

    private var phase = Phase.IDLE
    private val journal = mutableListOf<() -> Unit>()
    private val afterCommit = mutableListOf<() -> Unit>()

    val applying: Boolean
        get() = phase != Phase.IDLE

    fun record(undo: () -> Unit) {
        if (phase == Phase.APPLYING) {
            journal += undo
        }
    }

    fun afterCommit(action: () -> Unit) {
        if (phase == Phase.APPLYING) {
            afterCommit += action
        } else if (phase == Phase.IDLE) {
            action()
        }
    }

    fun apply(operations: List<RenderOperation>): Renderer.ApplyResult {
        if (operations.isEmpty()) return Renderer.ApplyResult.OK
        check(phase == Phase.IDLE) { "Nested native transactions are not supported" }

        try {
            preflight(operations)
        } catch (_: Throwable) {
            return Renderer.ApplyResult.REJECTED_KNOWN
        }

        val beforeDigest = digest()
        journal.clear()
        afterCommit.clear()
        phase = Phase.APPLYING
        try {
            operations.forEach(applyOperation)
        } catch (failure: Throwable) {
            phase = Phase.ROLLING_BACK
            var rollbackFailed = false
            var rollbackCause: Throwable? = null
            for (index in journal.indices.reversed()) {
                try {
                    journal[index]()
                } catch (t: Throwable) {
                    rollbackFailed = true
                    if (rollbackCause == null) {
                        rollbackCause = t
                    } else {
                        rollbackCause.addSuppressed(t)
                    }
                }
            }
            // Undo closures no longer swallow their own failures; surface the
            // true cause instead of erasing it below the UNKNOWN boundary.
            if (rollbackCause != null) {
                Log.w(
                    "RenderTransactionApplier",
                    "Rollback failed for ${operations.size} ops; forcing UNKNOWN snapshot",
                    rollbackCause,
                )
            }
            val result = if (rollbackFailed || journal.isEmpty() || digest() != beforeDigest) {
                Renderer.ApplyResult.UNKNOWN
            } else {
                Renderer.ApplyResult.PARTIAL
            }
            journal.clear()
            afterCommit.clear()
            phase = Phase.IDLE
            return result
        }

        // Presentation work begins only after every structural mutation has
        // succeeded. It can therefore never run against a rejected tree.
        phase = Phase.IDLE
        journal.clear()
        val acceptedActions = afterCommit.toList()
        afterCommit.clear()
        return try {
            acceptedActions.forEach { it() }
            Renderer.ApplyResult.OK
        } catch (_: Throwable) {
            // The structural tree is accepted but presentation state is not
            // known. Reporting UNKNOWN forces a complete framework snapshot.
            Renderer.ApplyResult.UNKNOWN
        } finally {
            journal.clear()
            afterCommit.clear()
            phase = Phase.IDLE
        }
    }
}
