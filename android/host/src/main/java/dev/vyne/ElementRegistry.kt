/**
 * Registry that maps Python element kinds to Android View factories.
 *
 * Each `ElementSpec` encodes three things:
 * - **create**: a factory that produces the View instance.
 * - **props**: per-prop handlers invoked when Python sends `set_prop`.
 * - **removeProps**: handlers invoked when Python sends `remove_prop` —
 *   needed because removing a prop generally means resetting to a sensible
 *   default, not just nulling a field.
 * - **events**: per-event attach hooks for extension-specific events. Each
 *   hook receives the View and an emit callback and returns a detach lambda.
 *
 * The `PropContext` carries an element ID and callbacks for resetting values
 * to their defaults (e.g., text color/size reset to the theme default, not
 * to 0 or transparent).
 *
 * Registration lifecycle (single source of truth):
 * 1. Core widgets register via `registerNativeWidgets`.
 * 2. Extensions register via the generated `registerAppExtensions`.
 * 3. `freeze()` locks the registry; the Renderer then uses it read-only.
 *    Python queries `extensionKinds()` at startup and builds its validation
 *    tables from this registry — no Python-side declaration, no drift.
 */
package dev.vyne

import android.content.Context
import android.view.View
import dev.vyne.generated.ElementContracts

internal data class ElementContext(
    val context: Context,
)

internal data class PropContext(
    val resetTextColor: (View) -> Unit = {},
    val resetTextSize: (View) -> Unit = {},
)

/** Bridge-safe description of one extension kind for the Python query. */
internal data class ExtensionKindInfo(
    val props: Set<String>,
    val events: Set<String>,
    val container: Boolean,
)

/**
 * One extension event hook: `(view, emit) -> detach`.
 *
 * The hook installs the native listener (calling `emit(payload)` when the
 * event fires) and returns a lambda that uninstalls it. Core events keep
 * their dedicated `Renderer.attachListener` when-block; extension events
 * fall back to the spec's hooks.
 */
internal typealias ExtensionEventHook =
    (view: View, emit: (payload: Map<String, Any?>) -> Unit) -> () -> Unit

internal data class ElementSpec(
    val kind: String,
    val create: (ElementContext) -> View,
    /**
     * One handler per prop. Removal is the SAME handler with a null value:
     * each handler owns its default in one place (Python already drops
     * explicit nulls before the wire, so null always means removal here).
     */
    val props: Map<String, (PropContext, View, Any?) -> Unit> = emptyMap(),
    val events: Map<String, ExtensionEventHook> = emptyMap(),
    /**
     * True when the native view is a ViewGroup and accepts children.
     * Leaf extension views (a plain View) must leave this false — the
     * Python side enforces it via max_children=0 in the synced contract.
     */
    val container: Boolean = false,
)

internal class ElementRegistry {
    private val specs = mutableMapOf<String, ElementSpec>()
    private var frozen = false

    /** Register one kind spec. Rejects duplicates (core or extension). */
    fun register(spec: ElementSpec) {
        check(!frozen) { "ElementRegistry is frozen; cannot register ${spec.kind}" }
        val existing = specs.putIfAbsent(spec.kind, spec)
        check(existing == null) { "Duplicate element kind: ${spec.kind}" }
    }

    /** Lock the registry. Registration after freeze is a programming error. */
    fun freeze() {
        frozen = true
    }

    val isFrozen: Boolean
        get() = frozen

    fun get(kind: String): ElementSpec {
        return specs[kind] ?: error("Unsupported view kind: $kind")
    }

    fun hasKind(kind: String): Boolean = kind in specs

    fun allKinds(): Set<String> = specs.keys

    /**
     * Contract validity for preflight and prop dispatch.
     *
     * Core kinds validate against the generated ElementContracts (unchanged).
     * Extension kinds accept the generic prop set (shared by all core kinds,
     * derived as their intersection) plus the spec's widget-specific props.
     */
    fun isValidProp(name: String, kind: String): Boolean {
        val core = ElementContracts.ALL_PROPS_BY_KIND[kind]
        if (core != null) return name in core
        val spec = specs[kind] ?: return false
        return name in ElementContracts.GENERIC_PROPS || name in spec.props
    }

    /**
     * Event contract validity for listen/unlisten preflight.
     *
     * Core kinds keep today's behavior (any core event name is accepted;
     * attachListener's when-block owns core dispatch). Extension kinds are
     * validated against the spec's declared events so an unknown event is
     * rejected at preflight (REJECTED_KNOWN), never at apply time.
     */
    fun isValidEvent(kind: String, event: String): Boolean {
        // Core events validate against the generated per-kind applicability
        // (EventSpec.applies_to); extension events against the spec map.
        val core = ElementContracts.ALL_EVENTS_BY_KIND[kind]
        if (core != null) return event in core
        val spec = specs[kind] ?: return false
        return event in spec.events
    }

    /**
     * The query surface for Python: every non-core kind with its
     * widget-specific props and events. Generic props are not listed —
     * they apply to every kind by definition.
     */
    fun extensionKinds(): Map<String, ExtensionKindInfo> =
        specs
            .filterKeys { it !in ElementContracts.KINDS }
            .mapValues { (_, spec) ->
                ExtensionKindInfo(
                    props = spec.props.keys.toSet(),
                    events = spec.events.keys.toSet(),
                    container = spec.container,
                )
            }

    /**
     * Container capability for preflight: extension parents must declare
     * themselves containers before insert/move ops are accepted. Core kinds
     * are containers by contract (their allowlist governs children).
     */
    fun isContainer(kind: String): Boolean {
        if (kind in ElementContracts.KINDS) return true
        return specs[kind]?.container == true
    }
}
