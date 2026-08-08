package dev.vyne

/**
 * One installed listener: handler identity, delivery policy, and — for
 * extension events — the detach callback that uninstalls the native
 * listener. Core listeners have a null detach (the core `when` blocks in
 * Renderer own their attach/detach).
 */
internal data class ListenerRecord(
    val handler: Int,
    val delivery: String,
    val detach: (() -> Unit)? = null,
)

/**
 * Owns listener identity, delivery policy, and native event sequencing —
 * for CORE and EXTENSION events alike. One record per (node, event); all
 * lifecycle operations (replace, remove, clear) flow through this class so
 * extension detach callbacks can never leak or be invoked twice.
 */
internal class EventBindings {
    val records = mutableMapOf<Pair<Int, String>, ListenerRecord>()
    private var nextSequence = 1L

    fun nextEventSequence(): Long = nextSequence++

    /**
     * Remove every record for the given nodes and return their detach
     * callbacks. The caller decides WHEN to invoke them (accepted-commit
     * gating); on rollback the records are simply restored by the journal.
     */
    fun removeNodes(nodeIds: Set<Int>): List<() -> Unit> {
        val detaches =
            records.filterKeys { it.first in nodeIds }
                .values
                .mapNotNull { it.detach }
        records.keys.removeAll { it.first in nodeIds }
        return detaches
    }

    /** Remove every record and return the detach callbacks to invoke. */
    fun clear(): List<() -> Unit> {
        val detaches = records.values.mapNotNull { it.detach }
        records.clear()
        return detaches
    }
}
