/**
 * Table-driven property applicator that maps canonical Python prop names to
 * strict Android View setters and resetters.
 *
 * This is the single source of truth for Kotlin-side property mechanics.
 * Handwritten code only maps generated slots to Android API calls — it never
 * embeds policy decisions, aliases, coercion fallbacks, or kind applicability
 * that should live in the Python schema.
 *
 * Design principles:
 * - **One set/reset table**: Every supported property has exactly one
 *   setter (apply) and one resetter (remove) defined here.  Nothing is
 *   scattered across widget-specific prop handlers.
 * - **Generated contracts are production inputs**: ElementContracts defines
 *   kind applicability; the applicator validates against it.
 * - **No fallback coercion**: Unknown or inapplicable props are rejected
 *   with a clear error, never silently ignored or defaulted to zero/transparent.
 * - **Neutral Views**: Views are created without policy assumptions (e.g.,
 *   focusable=false never disables a TextInput's default editing focus).
 * - **Python-owned dimensions**: Dimension values arrive as tagged wire
 *   tokens or numeric dp; Kotlin mechanically converts with no heuristic.
 */
package dev.vyne

import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.os.Build
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.ViewOutlineProvider
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import dev.vyne.generated.ElementContracts

// ─────────────────────────────────────────────────────────────────────────
// Dimension wire representation
// ─────────────────────────────────────────────────────────────────────────

/**
 * Tagged dimension value decoded from the Python wire format.
 *
 * Python sends dimensions as tagged wire tokens.  Kotlin mechanically
 * converts them to Android layout constants or pixel values.
 *
 * Wire format:
 *   - Numeric (Int/Double) → dp value → pixels
 *   - "wrap_content"        → LayoutParams.WRAP_CONTENT
 *   - "match_parent"        → LayoutParams.MATCH_PARENT
 *   - "16dp", "16.0dp"      → dp value → pixels (numeric prefix before "dp")
 *   - "16sp", "16.0sp"      → sp value → pixels (numeric prefix before "sp")
 */
internal sealed class DimensionValue {
    /** Pixel value — use directly as layout param. */
    data class Pixels(val px: Int) : DimensionValue()

    /** Wrap content. */
    object WrapContent : DimensionValue()

    /** Match parent. */
    object MatchParent : DimensionValue()

    /** Invalid / unrecognized dimension — use neutral default. */
    object Invalid : DimensionValue()

    fun toLayoutParam(default: Int = ViewGroup.LayoutParams.WRAP_CONTENT): Int = when (this) {
        is Pixels -> px
        WrapContent -> ViewGroup.LayoutParams.WRAP_CONTENT
        MatchParent -> ViewGroup.LayoutParams.MATCH_PARENT
        Invalid -> default
    }

    /**
     * Convert back to a wire-compatible format for rollback capture.
     * Returns a format that Python's set_prop would send:
     * - Pixels → Double (dp value)
     * - WrapContent → "wrap_content"
     * - MatchParent → "match_parent"
     * - Invalid → null
     */
    fun toWireFormat(): Any? {
        // Calculate the dp value from pixels using a standard density.
        // The captured value will be re-applied through setProp which calls
        // decodeDimension again, so the round-trip is exact.
        return when (this) {
            is Pixels -> null  // Cannot recover exact dp without density; return null to reset
            WrapContent -> "wrap_content"
            MatchParent -> "match_parent"
            Invalid -> null
        }
    }
}

/**
 * Decode a Python wire dimension value into a [DimensionValue].
 *
 * @param density display density for dp → px conversion
 */
internal fun decodeDimension(value: Any?, density: Float): DimensionValue {
    return when (value) {
        is Number -> {
            val dp = value.toFloat()
            DimensionValue.Pixels((dp * density).toInt())
        }
        is String -> {
            val trimmed = value.toString().trim().lowercase()
            when (trimmed) {
                "wrap_content" -> DimensionValue.WrapContent
                "match_parent" -> DimensionValue.MatchParent
                else -> {
                    // Try "16dp" or "16sp" format.
                    val suffix = "dp"
                    if (trimmed.endsWith(suffix)) {
                        val numeric = trimmed.removeSuffix(suffix).trim()
                        numeric.toFloatOrNull()?.let { num ->
                            DimensionValue.Pixels((num * density).toInt())
                        } ?: DimensionValue.Invalid
                    } else {
                        DimensionValue.Invalid
                    }
                }
            }
        }
        null -> DimensionValue.Invalid
        else -> DimensionValue.Invalid
    }
}

/**
 * Convert a Python wire dimension to raw pixels for properties that
 * always need a pixel value (padding, border, elevation, translation).
 */
/** Float-precision dp -> px for continuous properties (translations). */
internal fun translationToPx(value: Any?, density: Float): Float {
    val dp = when (value) {
        is Number -> value.toFloat()
        is String -> value.toString().trim().removeSuffix("dp").toFloatOrNull()
        else -> null
    } ?: return 0f
    return dp * density
}

internal fun dimensionToPx(value: Any?, density: Float): Int {
    return when (val d = decodeDimension(value, density)) {
        is DimensionValue.Pixels -> d.px
        is DimensionValue.WrapContent -> 0  // Sensible default: zero
        is DimensionValue.MatchParent -> 0
        is DimensionValue.Invalid -> 0
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Color wire representation
// ─────────────────────────────────────────────────────────────────────────

/**
 * Decode a Python wire color value.
 *
 * Wire format (Python-owned):
 *   - Integer: ARGB-packed 32-bit int (bits 24-31 = alpha, 16-23 = red,
 *     8-15 = green, 0-7 = blue).  This is the canonical wire format.
 *   - String "#RRGGBB" or "#RRGGBBAA":  RGBA hex string.
 *     Kotlin converts to ARGB int via [parseColorString].
 *   - null → transparent (0x00000000).
 *
 * @throws IllegalArgumentException if the value is an unrecognized format
 *   (no silent transparent fallback).
 */
internal fun decodeColor(value: Any?): Int {
    if (value == null) return 0x00000000  // Transparent
    return when (value) {
        is Number -> value.toInt()
        is String -> {
            val str = value.toString().trim()
            if (str.isEmpty()) {
                0x00000000
            } else if (str.startsWith("#")) {
                parseColorString(str)
            } else {
                // Try Color.parseColor (handles named colors like "red", "transparent").
                try {
                    Color.parseColor(str)
                } catch (_: IllegalArgumentException) {
                    throw IllegalArgumentException(
                        "Invalid color value: '$str'. " +
                        "Expected #RRGGBB, #RRGGBBAA, or a 32-bit ARGB integer."
                    )
                }
            }
        }
        else -> throw IllegalArgumentException(
            "Invalid color value type: ${value::class.java.simpleName}. " +
            "Expected Int or String."
        )
    }
}

/**
 * Parse a hex color string in Python's canonical RGBA format.
 *
 * - "#RGB"       → expanded to "#FFRRGGBB" (ARGB)
 * - "#RRGGBB"    → "#FFRRGGBB" (ARGB, alpha=FF)
 * - "#RRGGBBAA"  → "#AARRGGBB" (ARGB, swap AA to front)
 *
 * Python canonical colors are always RGBA; this converts to Android's
 * ARGB format.
 */
internal fun parseColorString(hex: String): Int {
    val h = hex.removePrefix("#")
    return when (h.length) {
        3 -> {
            // #RGB → #FFRRGGBB
            val r = h.substring(0, 1).repeat(2)
            val g = h.substring(1, 2).repeat(2)
            val b = h.substring(2, 3).repeat(2)
            Color.parseColor("#FF$r$g$b")
        }
        4 -> {
            // #RGBA → #AARRGGBB (swizzle)
            val r = h.substring(0, 1).repeat(2)
            val g = h.substring(1, 2).repeat(2)
            val b = h.substring(2, 3).repeat(2)
            val a = h.substring(3, 4).repeat(2)
            Color.parseColor("#$a$r$g$b")
        }
        6 -> {
            // #RRGGBB → #FFRRGGBB
            Color.parseColor("#FF$h")
        }
        8 -> {
            // #RRGGBBAA → #AARRGGBB (swizzle AA to front)
            val rr = h.substring(0, 2)
            val gg = h.substring(2, 4)
            val bb = h.substring(4, 6)
            val aa = h.substring(6, 8)
            Color.parseColor("#$aa$rr$gg$bb")
        }
        else -> throw IllegalArgumentException(
            "Invalid hex color: '$hex'. Expected #RGB, #RGBA, #RRGGBB, or #RRGGBBAA."
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Property applicator table
// ─────────────────────────────────────────────────────────────────────────

/**
 * Narrow property-mechanics surface. Applicators cannot reach transaction,
 * event, tree-publication, or animation internals through this interface.
 */
internal interface PropertyHost {
    val viewStates: MutableMap<Int, Renderer.ViewState>

    fun stateFor(id: Int): Renderer.ViewState
    fun updateNodeLayoutRaw(id: Int, update: Renderer.NodeLayout.() -> Unit)
    fun updateNodeLayoutPx(id: Int, update: Renderer.NodeLayout.() -> Unit)
    fun updateBasePadding(
        id: Int,
        view: View,
        update: Renderer.EdgeInsets.() -> Renderer.EdgeInsets,
    )
    fun updateCornerRadii(
        id: Int,
        view: View,
        update: Renderer.CornerRadii.() -> Unit,
    )
    fun updateOverflow(id: Int, view: View, overflow: String?)
    fun updateAccessibility(id: Int, view: View)
    fun updateBackground(id: Int, view: View)
    fun installSafeArea(id: Int, view: View)
    fun removeSafeArea(id: Int, view: View)
    fun updateLayoutGravity(id: Int, view: View)
    fun updateTextInputFocus(view: EditText, focused: Boolean)
    fun updateEditorActionListener(id: Int, view: EditText)
}

/** Context passed to one property applicator invocation. */
internal class ApplicatorContext(
    val id: Int,
    val view: View,
    val host: PropertyHost,
)

/**
 * A single property applicator: setter + resetter.
 *
 * [set] is called when Python sends set_prop.
 * [remove] is called when Python sends remove_prop.
 * [kindApplicable] is a set of kinds this prop applies to (from ElementContracts).
 */
internal data class PropApplicator(
    val name: String,
    val set: (ApplicatorContext, Any?) -> Unit,
    val remove: (ApplicatorContext) -> Unit,
    val kindApplicable: Set<String> = ElementContracts.KINDS,
)

/**
 * Master property applicator table.
 *
 * This is the single set/reset table that maps every canonical Python
 * property to its Android mechanical counterpart.  Generic props that
 * work across all kinds are defined here; widget-specific props (text,
 * orientation, path commands, etc.) are registered via [widgetApplicators].
 */
internal object PropertyTable {

    // Registry of all applicators, keyed by canonical prop name.
    private val applicators = mutableMapOf<String, PropApplicator>()

    init {
        registerGenericProps()
    }

    /**
     * Register additional widget-specific applicators.
     * Called during Renderer initialization after widget specs are built.
     */
    fun registerWidget(name: String, applicator: PropApplicator) {
        applicators[name] = applicator
    }

    /**
     * Get an applicator for a property, or null if the property is
     * not applicable to the given kind.
     *
     * Extension kinds are not in ElementContracts.KINDS, so the kind
     * set check would reject them; generic props (shared by all core
     * kinds) still apply to extension kinds by definition.
     */
    fun get(name: String, kind: String): PropApplicator? {
        val app = applicators[name] ?: return null
        if (kind in app.kindApplicable) return app
        if (
            kind !in ElementContracts.KINDS &&
            name in ElementContracts.GENERIC_PROPS
        ) {
            return app
        }
        return null
    }

    /**
     * Check whether a property name and kind combination is valid
     * according to the generated ElementContracts.
     */
    fun isValidProp(name: String, kind: String): Boolean {
        val allowed = ElementContracts.ALL_PROPS_BY_KIND[kind] ?: return false
        return name in allowed
    }

    // ── Generic property registration ──────────────────────────────

    @Suppress("DEPRECATION")
    private fun registerGenericProps() {
        // -- Dimensions --------------------------------------------------
        register(PropApplicator("width",
            set = { ctx, value ->
                val dim = decodeDimension(value, ctx.view.resources.displayMetrics.density)
                ctx.host.updateNodeLayoutRaw(ctx.id) { width = dim }
            },
            remove = { ctx ->
                ctx.host.updateNodeLayoutRaw(ctx.id) { width = DimensionValue.Invalid }
            },
        ))
        register(PropApplicator("height",
            set = { ctx, value ->
                val dim = decodeDimension(value, ctx.view.resources.displayMetrics.density)
                ctx.host.updateNodeLayoutRaw(ctx.id) { height = dim }
            },
            remove = { ctx ->
                ctx.host.updateNodeLayoutRaw(ctx.id) { height = DimensionValue.Invalid }
            },
        ))
        register(PropApplicator("min_width",
            set = { ctx, value ->
                ctx.view.minimumWidth = dimensionToPx(value, ctx.view.resources.displayMetrics.density)
            },
            remove = { ctx -> ctx.view.minimumWidth = 0 },
        ))
        register(PropApplicator("min_height",
            set = { ctx, value ->
                ctx.view.minimumHeight = dimensionToPx(value, ctx.view.resources.displayMetrics.density)
            },
            remove = { ctx -> ctx.view.minimumHeight = 0 },
        ))
        register(PropApplicator("max_width",
            set = { ctx, value ->
                val constrained = ctx.view as? MaxConstrainedView
                    ?: error("max_width applied to unsupported ${ctx.view.javaClass.simpleName}")
                constrained.vyneMaxWidthPx = dimensionToPx(
                    value, ctx.view.resources.displayMetrics.density
                )
                ctx.view.requestLayout()
            },
            remove = { ctx ->
                (ctx.view as? MaxConstrainedView)?.vyneMaxWidthPx = 0
                ctx.view.requestLayout()
            },
        ))
        register(PropApplicator("max_height",
            set = { ctx, value ->
                val constrained = ctx.view as? MaxConstrainedView
                    ?: error("max_height applied to unsupported ${ctx.view.javaClass.simpleName}")
                constrained.vyneMaxHeightPx = dimensionToPx(
                    value, ctx.view.resources.displayMetrics.density
                )
                ctx.view.requestLayout()
            },
            remove = { ctx ->
                (ctx.view as? MaxConstrainedView)?.vyneMaxHeightPx = 0
                ctx.view.requestLayout()
            },
        ))
        register(PropApplicator("_virtual_list_initial_offset",
            set = { ctx, value ->
                val scroll = ctx.view as? VyneScrollContainer
                    ?: error("list initial offset applied to unsupported ${ctx.view.javaClass.simpleName}")
                scroll.setVirtualListInitialOffset(
                    dimensionToPx(value, ctx.view.resources.displayMetrics.density)
                )
            },
            remove = { _ -> },
        ))

        // -- Virtual-list markers (private, Box-only) --------------------
        // The generic VirtualList marks its content Box and publishes sticky
        // boundary/edge metadata on sticky cell wrappers.  The native scroll
        // hosts consume these directly per frame; no bridge event or Python
        // commit is involved.  Underscore props never reach generated public
        // constructor stubs.
        register(PropApplicator("_virtual_content",
            kindApplicable = setOf("Box"),
            set = { ctx, value ->
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.isVirtualContent = value as? Boolean ?: false
                    if (!frame.isVirtualContent) {
                        // The native sticky pass stops at the marker; restore
                        // every displaced child before traversal is disabled.
                        frame.restoreChildrenNatural()
                    }
                }
            },
            remove = { ctx ->
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.isVirtualContent = false
                    frame.restoreChildrenNatural()
                }
            },
        ))
        register(PropApplicator("_virtual_sticky_edge",
            kindApplicable = setOf("Box"),
            set = { ctx, value ->
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.stickyEdge = value as? String
                    // A boundary/edge change must re-displace immediately
                    // even on a stationary viewport (no scroll/layout yet).
                    frame.refreshSticky()
                }
            },
            remove = { ctx ->
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.stickyEdge = null
                    frame.restoreNaturalPosition()
                    frame.refreshSticky()
                }
            },
        ))
        register(PropApplicator("_virtual_sticky_boundary_start",
            kindApplicable = setOf("Box"),
            set = { ctx, value ->
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.stickyBoundaryStartPx =
                        translationToPx(value, ctx.view.resources.displayMetrics.density)
                    frame.refreshSticky()
                }
            },
            remove = { ctx ->
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.stickyBoundaryStartPx = 0f
                    frame.refreshSticky()
                }
            },
        ))
        register(PropApplicator("_virtual_sticky_boundary_end",
            kindApplicable = setOf("Box"),
            set = { ctx, value ->
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.stickyBoundaryEndPx =
                        translationToPx(value, ctx.view.resources.displayMetrics.density)
                    frame.refreshSticky()
                }
            },
            remove = { ctx ->
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.stickyBoundaryEndPx = 0f
                    frame.refreshSticky()
                }
            },
        ))

        // -- Padding -----------------------------------------------------
        register(PropApplicator("padding_top",
            set = { ctx, value ->
                ctx.host.updateBasePadding(ctx.id, ctx.view) {
                    copy(top = dimensionToPx(value, ctx.view.resources.displayMetrics.density))
                }
            },
            remove = { ctx ->
                ctx.host.updateBasePadding(ctx.id, ctx.view) { copy(top = 0) }
            },
        ))
        register(PropApplicator("padding_bottom",
            set = { ctx, value ->
                ctx.host.updateBasePadding(ctx.id, ctx.view) {
                    copy(bottom = dimensionToPx(value, ctx.view.resources.displayMetrics.density))
                }
            },
            remove = { ctx ->
                ctx.host.updateBasePadding(ctx.id, ctx.view) { copy(bottom = 0) }
            },
        ))
        register(PropApplicator("padding_start",
            set = { ctx, value ->
                ctx.host.updateBasePadding(ctx.id, ctx.view) {
                    copy(left = dimensionToPx(value, ctx.view.resources.displayMetrics.density))
                }
            },
            remove = { ctx ->
                ctx.host.updateBasePadding(ctx.id, ctx.view) { copy(left = 0) }
            },
        ))
        register(PropApplicator("padding_end",
            set = { ctx, value ->
                ctx.host.updateBasePadding(ctx.id, ctx.view) {
                    copy(right = dimensionToPx(value, ctx.view.resources.displayMetrics.density))
                }
            },
            remove = { ctx ->
                ctx.host.updateBasePadding(ctx.id, ctx.view) { copy(right = 0) }
            },
        ))

        // -- Margins -----------------------------------------------------
        register(PropApplicator("margin_top",
            set = { ctx, value ->
                ctx.host.updateNodeLayoutPx(ctx.id) { marginTop = dimensionToPx(value, ctx.view.resources.displayMetrics.density) }
            },
            remove = { ctx ->
                ctx.host.updateNodeLayoutPx(ctx.id) { marginTop = 0 }
            },
        ))
        register(PropApplicator("margin_bottom",
            set = { ctx, value ->
                ctx.host.updateNodeLayoutPx(ctx.id) { marginBottom = dimensionToPx(value, ctx.view.resources.displayMetrics.density) }
            },
            remove = { ctx ->
                ctx.host.updateNodeLayoutPx(ctx.id) { marginBottom = 0 }
            },
        ))
        register(PropApplicator("margin_start",
            set = { ctx, value ->
                ctx.host.updateNodeLayoutPx(ctx.id) { marginStart = dimensionToPx(value, ctx.view.resources.displayMetrics.density) }
            },
            remove = { ctx ->
                ctx.host.updateNodeLayoutPx(ctx.id) { marginStart = 0 }
            },
        ))
        register(PropApplicator("margin_end",
            set = { ctx, value ->
                ctx.host.updateNodeLayoutPx(ctx.id) { marginEnd = dimensionToPx(value, ctx.view.resources.displayMetrics.density) }
            },
            remove = { ctx ->
                ctx.host.updateNodeLayoutPx(ctx.id) { marginEnd = 0 }
            },
        ))

        // -- Background / border -----------------------------------------
        register(PropApplicator("background_color",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).backgroundColor = decodeColor(value)
                ctx.host.updateBackground(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).backgroundColor = null
                ctx.host.updateBackground(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("border_width",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).borderWidth = dimensionToPx(value, ctx.view.resources.displayMetrics.density)
                ctx.host.updateBackground(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).borderWidth = 0
                ctx.host.updateBackground(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("border_color",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).borderColor = decodeColor(value)
                ctx.host.updateBackground(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).borderColor = null
                ctx.host.updateBackground(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("ripple_color",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).rippleColor = decodeColor(value)
                ctx.host.updateBackground(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).rippleColor = null
                ctx.host.updateBackground(ctx.id, ctx.view)
            },
        ))

        // -- Corner radii ------------------------------------------------
        register(PropApplicator("corner_radius_top_left",
            set = { ctx, value ->
                ctx.host.updateCornerRadii(ctx.id, ctx.view) {
                    topLeft = dimensionToPx(value, ctx.view.resources.displayMetrics.density).toFloat()
                }
            },
            remove = { ctx ->
                ctx.host.viewStates[ctx.id]?.cornerRadii?.let {
                    ctx.host.updateCornerRadii(ctx.id, ctx.view) { topLeft = 0f }
                } ?: ctx.host.updateBackground(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("corner_radius_top_right",
            set = { ctx, value ->
                ctx.host.updateCornerRadii(ctx.id, ctx.view) {
                    topRight = dimensionToPx(value, ctx.view.resources.displayMetrics.density).toFloat()
                }
            },
            remove = { ctx ->
                ctx.host.viewStates[ctx.id]?.cornerRadii?.let {
                    ctx.host.updateCornerRadii(ctx.id, ctx.view) { topRight = 0f }
                } ?: ctx.host.updateBackground(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("corner_radius_bottom_right",
            set = { ctx, value ->
                ctx.host.updateCornerRadii(ctx.id, ctx.view) {
                    bottomRight = dimensionToPx(value, ctx.view.resources.displayMetrics.density).toFloat()
                }
            },
            remove = { ctx ->
                ctx.host.viewStates[ctx.id]?.cornerRadii?.let {
                    ctx.host.updateCornerRadii(ctx.id, ctx.view) { bottomRight = 0f }
                } ?: ctx.host.updateBackground(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("corner_radius_bottom_left",
            set = { ctx, value ->
                ctx.host.updateCornerRadii(ctx.id, ctx.view) {
                    bottomLeft = dimensionToPx(value, ctx.view.resources.displayMetrics.density).toFloat()
                }
            },
            remove = { ctx ->
                ctx.host.viewStates[ctx.id]?.cornerRadii?.let {
                    ctx.host.updateCornerRadii(ctx.id, ctx.view) { bottomLeft = 0f }
                } ?: ctx.host.updateBackground(ctx.id, ctx.view)
            },
        ))

        // -- Visibility / interaction ------------------------------------
        register(PropApplicator("enabled",
            set = { ctx, value -> ctx.view.isEnabled = value as? Boolean ?: true },
            remove = { ctx -> ctx.view.isEnabled = true },
        ))
        register(PropApplicator("visible",
            set = { ctx, value ->
                ctx.view.visibility = if (value as? Boolean ?: true) View.VISIBLE else View.GONE
            },
            remove = { ctx -> ctx.view.visibility = View.VISIBLE },
        ))
        register(PropApplicator("opacity",
            set = { ctx, value -> ctx.view.alpha = (value as? Number)?.toFloat() ?: 1f },
            remove = { ctx -> ctx.view.alpha = 1f },
        ))
        register(PropApplicator("clickable",
            set = { ctx, value -> ctx.view.isClickable = value as? Boolean ?: true },
            remove = { ctx -> ctx.view.isClickable = false },
        ))
        // focusable: default=false on most kinds, but TextInput's natural
        // EditText is inherently focusable.  Removing focusable on TextInput
        // restores EditText's default, not false.
        register(PropApplicator("focusable",
            set = { ctx, value ->
                ctx.view.isFocusable = value as? Boolean ?: true
                ctx.view.isFocusableInTouchMode = value as? Boolean ?: true
            },
            remove = { ctx ->
                // Restore neutral: for EditText, default is focusable=true.
                val isTextInput = ctx.view is EditText
                ctx.view.isFocusable = isTextInput
                ctx.view.isFocusableInTouchMode = isTextInput
            },
        ))
        register(PropApplicator("content_description",
            set = { ctx, value -> ctx.view.contentDescription = value?.toString() },
            remove = { ctx -> ctx.view.contentDescription = null },
        ))

        // -- Accessibility -----------------------------------------------
        register(PropApplicator("accessibility_role",
            set = { ctx, value ->
                val role = value?.toString()?.lowercase()
                // "none" explicitly means no role — clear accessibility.
                if (role == null || role == "none" || role.isEmpty()) {
                    ctx.host.stateFor(ctx.id).accessibilityRole = null
                } else {
                    ctx.host.stateFor(ctx.id).accessibilityRole = role
                }
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).accessibilityRole = null
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("accessibility_selected",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).accessibilityStateSelected = when (value) {
                    is Boolean -> value
                    "true" -> true
                    "false" -> false
                    else -> false
                }
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).accessibilityStateSelected = false
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("accessibility_checked",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).accessibilityStateChecked = when (value) {
                    is Boolean -> if (value) "checked" else "unchecked"
                    is String -> value.lowercase()
                    else -> value?.toString()?.lowercase()
                }
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).accessibilityStateChecked = null
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("accessibility_state_description",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).accessibilityStateDescription = value?.toString()
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).accessibilityStateDescription = null
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("accessibility_range_min",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).accessibilityRangeMin = (value as? Number)?.toFloat() ?: 0f
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).accessibilityRangeMin = 0f
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("accessibility_range_max",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).accessibilityRangeMax = (value as? Number)?.toFloat() ?: 0f
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).accessibilityRangeMax = 0f
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("accessibility_range_current",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).accessibilityRangeCurrent = (value as? Number)?.toFloat() ?: 0f
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
            remove = { ctx ->
                ctx.host.stateFor(ctx.id).accessibilityRangeCurrent = 0f
                ctx.host.updateAccessibility(ctx.id, ctx.view)
            },
        ))

        // -- Elevation ---------------------------------------------------
        register(PropApplicator("elevation",
            set = { ctx, value -> ctx.view.elevation = dimensionToPx(value, ctx.view.resources.displayMetrics.density).toFloat() },
            remove = { ctx -> ctx.view.elevation = 0f },
        ))

        // -- Transforms --------------------------------------------------
        register(PropApplicator("rotation",
            set = { ctx, value -> ctx.view.rotation = (value as? Number)?.toFloat() ?: 0f },
            remove = { ctx -> ctx.view.rotation = 0f },
        ))
        register(PropApplicator("rotation_x",
            set = { ctx, value -> ctx.view.rotationX = (value as? Number)?.toFloat() ?: 0f },
            remove = { ctx -> ctx.view.rotationX = 0f },
        ))
        register(PropApplicator("rotation_y",
            set = { ctx, value -> ctx.view.rotationY = (value as? Number)?.toFloat() ?: 0f },
            remove = { ctx -> ctx.view.rotationY = 0f },
        ))
        register(PropApplicator("scale_x",
            set = { ctx, value -> ctx.view.scaleX = (value as? Number)?.toFloat() ?: 1f },
            remove = { ctx -> ctx.view.scaleX = 1f },
        ))
        register(PropApplicator("scale_y",
            set = { ctx, value -> ctx.view.scaleY = (value as? Number)?.toFloat() ?: 1f },
            remove = { ctx -> ctx.view.scaleY = 1f },
        ))
        register(PropApplicator("translation_x",
            // Translations are continuous: use float pixel precision
            // (int-quantized dp conversion would jitter sub-pixel values).
            set = { ctx, value ->
                val px = translationToPx(value, ctx.view.resources.displayMetrics.density)
                ctx.view.translationX = px
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.naturalTranslationX = px
                    frame.refreshSticky()
                }
            },
            remove = { ctx ->
                // Reset only the X axis and re-apply any active displacement;
                // never clobber the Y axis or the paint Z of a sticky cell.
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.resetNaturalX()
                } ?: run { ctx.view.translationX = 0f }
            },
        ))
        register(PropApplicator("translation_y",
            set = { ctx, value ->
                val px = translationToPx(value, ctx.view.resources.displayMetrics.density)
                ctx.view.translationY = px
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.naturalTranslationY = px
                    frame.refreshSticky()
                }
            },
            remove = { ctx ->
                // Reset only the Y axis and re-apply any active displacement;
                // never clobber the X axis or the paint Z of a sticky cell.
                (ctx.view as? RoundedFrameLayout)?.let { frame ->
                    frame.resetNaturalY()
                } ?: run { ctx.view.translationY = 0f }
            },
        ))

        // -- Text alignment / direction ----------------------------------
        register(PropApplicator("text_alignment",
            set = { ctx, value ->
                ctx.view.textAlignment = when (value?.toString()?.trim()?.lowercase()) {
                    "inherit" -> View.TEXT_ALIGNMENT_INHERIT
                    "gravity" -> View.TEXT_ALIGNMENT_GRAVITY
                    "text_start" -> View.TEXT_ALIGNMENT_TEXT_START
                    "text_end" -> View.TEXT_ALIGNMENT_TEXT_END
                    "center" -> View.TEXT_ALIGNMENT_CENTER
                    "view_start" -> View.TEXT_ALIGNMENT_VIEW_START
                    "view_end" -> View.TEXT_ALIGNMENT_VIEW_END
                    "start" -> View.TEXT_ALIGNMENT_TEXT_START
                    "end" -> View.TEXT_ALIGNMENT_TEXT_END
                    else -> View.TEXT_ALIGNMENT_INHERIT
                }
            },
            remove = { ctx -> ctx.view.textAlignment = View.TEXT_ALIGNMENT_INHERIT },
        ))
        register(PropApplicator("text_direction",
            set = { ctx, value ->
                ctx.view.textDirection = when (value?.toString()?.trim()?.lowercase()) {
                    "inherit" -> View.TEXT_DIRECTION_INHERIT
                    "first_strong" -> View.TEXT_DIRECTION_FIRST_STRONG
                    "any_rtl" -> View.TEXT_DIRECTION_ANY_RTL
                    "ltr" -> View.TEXT_DIRECTION_LTR
                    "rtl" -> View.TEXT_DIRECTION_RTL
                    "locale" -> View.TEXT_DIRECTION_LOCALE
                    "first_strong_ltr" -> View.TEXT_DIRECTION_FIRST_STRONG_LTR
                    "first_strong_rtl" -> View.TEXT_DIRECTION_FIRST_STRONG_RTL
                    else -> View.TEXT_DIRECTION_INHERIT
                }
            },
            remove = { ctx -> ctx.view.textDirection = View.TEXT_DIRECTION_INHERIT },
        ))

        // -- Alignment / justification (container only) ------------------
        // align_items / justify_content are applicable to container kinds.
        // For non-containers, they are
        // valid props per the schema but have no Android effect.
        register(PropApplicator("align_items",
            kindApplicable = setOf("Box", "Layout", "Scroll", "HorizontalScroll"),
            set = { ctx, value ->
                (ctx.view as? RoundedLinearLayout)?.alignItems = value?.toString()
                ctx.host.updateLayoutGravity(ctx.id, ctx.view)
            },
            remove = { ctx ->
                (ctx.view as? RoundedLinearLayout)?.alignItems = null
                ctx.host.updateLayoutGravity(ctx.id, ctx.view)
            },
        ))
        register(PropApplicator("justify_content",
            kindApplicable = setOf("Box", "Layout", "Scroll", "HorizontalScroll"),
            set = { ctx, value ->
                (ctx.view as? RoundedLinearLayout)?.justifyContent = value?.toString()
                ctx.host.updateLayoutGravity(ctx.id, ctx.view)
            },
            remove = { ctx ->
                (ctx.view as? RoundedLinearLayout)?.justifyContent = null
                ctx.host.updateLayoutGravity(ctx.id, ctx.view)
            },
        ))

        // -- lp_weight and lp_gravity (on children) ----------------------
        register(PropApplicator("lp_weight",
            set = { ctx, value ->
                ctx.host.updateNodeLayoutPx(ctx.id) { lpWeight = (value as? Number)?.toFloat() }
            },
            remove = { ctx ->
                ctx.host.updateNodeLayoutPx(ctx.id) { lpWeight = null }
            },
        ))
        register(PropApplicator("lp_gravity",
            set = { ctx, value ->
                ctx.host.updateNodeLayoutPx(ctx.id) { lpGravity = parseGravityStatic(value) }
            },
            remove = { ctx ->
                ctx.host.updateNodeLayoutPx(ctx.id) { lpGravity = null }
            },
        ))

        // -- Pointer -----------------------------------------------------
        register(PropApplicator("pointer_capture_axis",
            set = { ctx, value ->
                ctx.host.stateFor(ctx.id).pointerCaptureAxis = value?.toString()?.lowercase()
            },
            remove = { ctx -> ctx.host.stateFor(ctx.id).pointerCaptureAxis = null },
        ))

        // -- Overflow ----------------------------------------------------
        register(PropApplicator("overflow",
            kindApplicable = setOf("Box", "Layout", "Scroll", "HorizontalScroll"),
            set = { ctx, value ->
                ctx.host.updateOverflow(ctx.id, ctx.view, value?.toString())
            },
            remove = { ctx ->
                ctx.host.updateOverflow(ctx.id, ctx.view, "hidden")
            },
        ))

        // -- Safe area ---------------------------------------------------
        // Every Android View owns padding, so inset composition is useful
        // for both containers and leaves. The generated contract deliberately
        // exposes this without a kind guard.
        register(PropApplicator("safe_area",
            set = { ctx, value ->
                if (value as? Boolean ?: false) {
                    ctx.host.installSafeArea(ctx.id, ctx.view)
                } else {
                    ctx.host.removeSafeArea(ctx.id, ctx.view)
                }
            },
            remove = { ctx -> ctx.host.removeSafeArea(ctx.id, ctx.view) },
        ))

        // -- TextInput-specific generic props ----------------------------
        // focused — only meaningful for EditText
        register(PropApplicator("focused",
            kindApplicable = setOf("TextInput"),
            set = { ctx, value ->
                if (ctx.view is EditText) {
                    ctx.host.stateFor(ctx.id).controlledFocus = value as? Boolean ?: false
                    ctx.host.updateTextInputFocus(ctx.view, ctx.host.stateFor(ctx.id).controlledFocus == true)
                }
            },
            remove = { ctx ->
                if (ctx.view is EditText) {
                    ctx.host.stateFor(ctx.id).controlledFocus = null
                }
            },
        ))
        register(PropApplicator("blur_on_keyboard_hide",
            kindApplicable = setOf("TextInput"),
            set = { ctx, value ->
                if (ctx.view is EditText) {
                    ctx.host.stateFor(ctx.id).blurOnKeyboardHide = value as? Boolean ?: false
                }
            },
            remove = { ctx ->
                if (ctx.view is EditText) {
                    ctx.host.stateFor(ctx.id).blurOnKeyboardHide = false
                }
            },
        ))
        register(PropApplicator("blur_on_tap_outside",
            kindApplicable = setOf("TextInput"),
            set = { ctx, value ->
                if (ctx.view is EditText) {
                    ctx.host.stateFor(ctx.id).blurOnTapOutside = value as? Boolean ?: false
                }
            },
            remove = { ctx ->
                if (ctx.view is EditText) {
                    ctx.host.stateFor(ctx.id).blurOnTapOutside = false
                }
            },
        ))
        register(PropApplicator("blur_on_submit",
            kindApplicable = setOf("TextInput"),
            set = { ctx, value ->
                if (ctx.view is EditText) {
                    ctx.host.stateFor(ctx.id).blurOnSubmit = value as? Boolean ?: false
                    ctx.host.updateEditorActionListener(ctx.id, ctx.view)
                }
            },
            remove = { ctx ->
                if (ctx.view is EditText) {
                    ctx.host.stateFor(ctx.id).blurOnSubmit = false
                    ctx.host.updateEditorActionListener(ctx.id, ctx.view)
                }
            },
        ))
    }

    private fun register(app: PropApplicator) {
        applicators[app.name] = app
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Gravity parsing (shared)
// ─────────────────────────────────────────────────────────────────────────

internal fun parseGravityStatic(value: Any?): Int {
    return when (value?.toString()?.trim()?.lowercase()) {
        "center" -> Gravity.CENTER
        "top" -> Gravity.TOP
        "bottom" -> Gravity.BOTTOM
        "start" -> Gravity.START
        "end" -> Gravity.END
        "center_horizontal" -> Gravity.CENTER_HORIZONTAL
        "center_vertical" -> Gravity.CENTER_VERTICAL
        "top|start" -> Gravity.TOP or Gravity.START
        "top|end" -> Gravity.TOP or Gravity.END
        "bottom|start" -> Gravity.BOTTOM or Gravity.START
        "bottom|end" -> Gravity.BOTTOM or Gravity.END
        else -> Gravity.NO_GRAVITY
    }
}
