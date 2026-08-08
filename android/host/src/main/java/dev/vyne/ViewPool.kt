package dev.vyne

import android.view.View

/**
 * Pool of detached views for cell reuse.
 *
 * Python keeps deciding which window is rendered; this pool only makes
 * mounting that window cheap by reusing views instead of creating them.
 * Pool entries are keyed by element kind; only stateless display kinds are
 * pooled, so a reused view never carries scroll, input, or canvas state.
 *
 * Pool mutations are journalled like any structural operation: `put` happens
 * on remove-apply, `take` on create-apply, and both are undone on rollback,
 * so the pool always mirrors exactly the views that are NOT in the tree.
 */
internal class ViewPool(
    private val maxPerKind: Int,
) {
    internal data class Entry(
        val view: View,
        val resetProps: List<String>,
    )

    private val pools = mutableMapOf<String, ArrayDeque<Entry>>()

    val size: Int
        get() = pools.values.sumOf { it.size }

    fun sizeOf(kind: String): Int = pools[kind]?.size ?: 0

    /** Pop the most recently pooled entry of this kind, or null. */
    fun take(kind: String): Entry? = pools[kind]?.removeLastOrNull()

    /** Push one detached view; the entry is dropped when the pool is full. */
    fun put(kind: String, view: View, resetProps: List<String>) {
        val queue = pools.getOrPut(kind) { ArrayDeque() }
        if (queue.size < maxPerKind) {
            queue.addLast(Entry(view, resetProps))
        }
    }

    /** Remove one specific entry (rollback of a pooled view's removal). */
    fun remove(view: View) {
        for (queue in pools.values) {
            if (queue.removeAll { it.view === view }) break
        }
    }

    fun clear() {
        pools.clear()
    }

    companion object {
        /** Kinds whose views carry no state and are safe to reuse. */
        val RECYCLABLE_KINDS: Set<String> = setOf("Box", "Layout", "Text")
    }
}
