package dev.vyne

import android.view.View
import android.widget.FrameLayout
import org.json.JSONArray
import org.json.JSONObject

/** Deep-copy a JSON bridge container so stored values cannot be mutated
 * through the live object graph (design-pattern #2). */
internal fun deepCopyBridgeValue(value: Any?): Any? = when (value) {
    is JSONArray -> JSONArray(value.toString())
    is JSONObject -> JSONObject(value.toString())
    is Map<*, *> -> LinkedHashMap<String, Any?>().apply {
        for ((key, item) in value) this[key.toString()] = deepCopyBridgeValue(item)
    }
    is List<*> -> value.map { deepCopyBridgeValue(it) }
    else -> value
}

/**
 * Accepted-prop authority (design-pattern #2).
 *
 * One record per (node, prop) holding what the framework accepted:
 * presence, the accepted wire value, and slot-keyed live presentation
 * values (e.g. Canvas draw ops that live outside the wire form).
 * This replaces the appliedProps shadow AND the capturePropValue
 * live-view when-switch — one rollback algorithm for all kinds.
 */
internal class PropMemento(
    var present: Boolean,
    var acceptedWireValue: Any?,
    val livePresentationValues: MutableMap<String, Any?> = mutableMapOf(),
) {
    /** Deep snapshot for undo closures: a later transaction's rollback
     * restores exactly this accepted state. */
    fun snapshot(): PropMemento =
        PropMemento(
            present,
            deepCopyBridgeValue(acceptedWireValue),
            livePresentationValues
                .mapValuesTo(mutableMapOf()) { (_, v) -> deepCopyBridgeValue(v) },
        )
}

/**
 * Authoritative native-tree storage.
 *
 * Keeping these indexes together makes their shared lifetime explicit and
 * gives transaction, property, and event code one tree owner. Renderer may
 * orchestrate mutations, but it no longer independently owns parallel maps.
 */
internal class NativeTree(root: FrameLayout) {
    val views = mutableMapOf<Int, View>(0 to root)
    val specs = mutableMapOf<Int, ElementSpec>()
    val parentOf = mutableMapOf<Int, Int>()
    val childrenOf = mutableMapOf<Int, MutableSet<Int>>()
    val viewStates = mutableMapOf<Int, Renderer.ViewState>()

    /**
     * Accepted-prop mementos per (node, prop) — the single authority for
     * presence, accepted wire value, and live presentation values.
     * Updated only by the accepted-wire set/remove paths (through
     * recordAcceptedProp), so rollback is exact for every kind.
     */
    val propMementos = mutableMapOf<Int, MutableMap<String, PropMemento>>()

    fun resetToRoot() {
        val root = views.getValue(0)
        views.clear()
        views[0] = root
        specs.clear()
        parentOf.clear()
        childrenOf.clear()
        viewStates.clear()
        propMementos.clear()
    }
}
