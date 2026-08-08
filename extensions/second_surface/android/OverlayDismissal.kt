/**
 * second_surface example — dismissal routing.
 *
 * The Python side drives attach-point teardown through a plain prop
 * (dismiss_requested on OverlayHost/PromptHost). The prop handler receives
 * the element's View; this routes up the parent chain to the attach-point
 * root (tagged by registering the root here) and invokes the consumer's
 * teardown action. Extension-owned, window-agnostic.
 */
package dev.vyne.ext.second_surface

import android.view.View
import java.util.concurrent.ConcurrentHashMap

object OverlayDismissal {
    private val actionsByRoot = ConcurrentHashMap<View, () -> Unit>()

    /** Register the teardown action for one attach-point root view. */
    fun register(root: View, action: () -> Unit) {
        actionsByRoot[root] = action
    }

    /** Drop the registration (root detached / activity destroyed). */
    fun unregister(root: View) {
        actionsByRoot.remove(root)
    }

    /** The teardown action for the attach point containing *view*, or null. */
    fun find(view: View): (() -> Unit)? {
        var current: View? = view
        while (current != null) {
            actionsByRoot[current]?.let { return it }
            current = current.parent as? View
        }
        return null
    }
}
