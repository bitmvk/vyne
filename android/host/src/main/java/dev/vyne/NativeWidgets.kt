/**
 * Widget registration: maps Python element kinds to Android View factories.
 *
 * This is the only place where Python concepts ("Box", "Text", "Path")
 * are wired to concrete Android classes.  Each registration defines:
 * - The View subclass to instantiate.
 * - Prop handlers for widget-specific properties (e.g., "text" on Text).
 * - Remove-prop handlers for resetting values (text → "", color → theme default).
 *
 * Generic properties (width, height, background, corner_radius, etc.) are
 * handled by the Renderer's `handleGenericProp` — they don't appear here.
 */
package dev.vyne

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.RectF
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.graphics.Paint
import dev.vyne.generated.registerAppExtensions
import org.json.JSONArray
import kotlin.math.roundToInt

/**
 * Build the process registry: core widgets, then extensions (generated
 * registrant), then freeze. Used by the Renderer default and by tests.
 */
internal fun defaultRegistry(context: Context): ElementRegistry =
    ElementRegistry().apply {
        registerNativeWidgets(this)
        registerAppExtensions(context, this)
        freeze()
    }

@SuppressLint("DiscouragedApi") // User drawable names are runtime data, not host R symbols.
internal fun registerNativeWidgets(registry: ElementRegistry) {
    // Box → FrameLayout that supports rounded corners via dispatchDraw.
    registry.register(ElementSpec(
        kind = "Box",
        create = { RoundedFrameLayout(it.context) },
    ))

    // Layout → RoundedLinearLayout. Widget-specific orientation is handled
    // here; shared alignment properties live exclusively in PropertyTable.
    registry.register(ElementSpec(
        kind = "Layout",
        create = {
            RoundedLinearLayout(it.context).apply {
                orientation = LinearLayout.VERTICAL
            }
        },
        props = mapOf(
            "orientation" to { _, view, value ->
                if (view is LinearLayout) {
                    view.orientation = if (value?.toString() == "horizontal") {
                        LinearLayout.HORIZONTAL
                    } else {
                        LinearLayout.VERTICAL
                    }
                    updateLinearLayoutGravity(view)
                }
            },
        ),
    ))

    // Vertical and horizontal scroll mechanics use distinct native classes.
    registry.register(ElementSpec(
        kind = "Scroll",
        create = { RoundedScrollView(it.context) },
    ))
    registry.register(ElementSpec(
        kind = "HorizontalScroll",
        create = { RoundedHorizontalScrollView(it.context) },
    ))

    // Text → Android TextView.  line_height is emulated via setLineSpacing
    // because Android TextView doesn't have a direct line-height property.
    registry.register(ElementSpec(
        kind = "Text",
        create = { TextView(it.context) },
        props = mapOf(
            "text" to { _, view, value ->
                if (view is TextView) view.text = value?.toString().orEmpty()
            },
            "text_color" to { context, view, value ->
                if (view is TextView) {
                    if (value == null) context.resetTextColor(view)
                    else view.setTextColor(parseColor(value))
                }
            },
            "font_size" to { context, view, value ->
                if (view is TextView) {
                    if (value == null) context.resetTextSize(view)
                    else view.textSize = toSp(value, 14f)
                }
            },
            "line_height" to { _, view, value ->
                if (view is TextView) {
                    if (value == null) view.setLineSpacing(0f, 1f)
                    else setTextLineHeight(view, value)
                }
            },
            "include_font_padding" to { _, view, value ->
                if (view is TextView) view.includeFontPadding = value as? Boolean ?: true
            },
        ),
    ))

    registry.register(ElementSpec(
        kind = "TextInput",
        create = { EditText(it.context) },
        props = mapOf(
            "text" to { _, view, value ->
                if (view is EditText) view.setText(value?.toString().orEmpty())
            },
            "hint" to { _, view, value ->
                if (view is EditText) view.hint = value?.toString().orEmpty()
            },
            "text_color" to { context, view, value ->
                if (view is EditText) {
                    if (value == null) context.resetTextColor(view)
                    else view.setTextColor(parseColor(value))
                }
            },
            "font_size" to { context, view, value ->
                if (view is EditText) {
                    if (value == null) context.resetTextSize(view)
                    else view.textSize = toSp(value, 14f)
                }
            },
        ),
    ))

    // Image → ImageView.  Source is resolved as a drawable resource by name.
    // Image loading/resource errors are separate from explicit accessibility
    // descriptions — a load failure never overwrites content_description.
    registry.register(ElementSpec(
        kind = "Image",
        create = { ImageView(it.context) },
        props = mapOf(
            "source" to { _, view, value ->
                if (view is ImageView) {
                    val name = value?.toString().orEmpty()
                    if (name.isEmpty()) {
                        view.setImageDrawable(null)
                    } else {
                        val resourceId = view.context.resources.getIdentifier(
                            name, "drawable", view.context.packageName
                        )
                        if (resourceId != 0) {
                            view.setImageResource(resourceId)
                        } else {
                            view.setImageDrawable(null)
                        }
                    }
                }
            },
            "scale_type" to { _, view, value ->
                if (view is ImageView) {
                    view.scaleType = when (value?.toString()) {
                        "center_crop" -> ImageView.ScaleType.CENTER_CROP
                        "fit_center" -> ImageView.ScaleType.FIT_CENTER
                        "center_inside" -> ImageView.ScaleType.CENTER_INSIDE
                        else -> ImageView.ScaleType.FIT_CENTER
                    }
                }
            },
        ),
    ))

    // Path → Custom PathView that renders pre-compiled SVG path commands.
    registry.register(ElementSpec(
        kind = "Path",
        create = { PathView(it.context) },
        props = mapOf(
            "commands" to { _, view, value ->
                if (view is PathView) {
                    view.commands = if (value == null) JSONArray() else value as? JSONArray ?: JSONArray()
                }
            },
            "stroke_color" to { _, view, value ->
                if (view is PathView) {
                    view.strokeColor =
                        if (value == null) 0xFF000000.toInt() else parseColor(value)
                }
            },
            "stroke_width" to { _, view, value ->
                if (view is PathView) {
                    val density = view.context.resources.displayMetrics.density
                    view.strokeWidth = toFloat(value, 2f) * density
                }
            },
            "stroke_line_cap" to { _, view, value ->
                if (view is PathView) view.strokeCap = parseStrokeCap(value?.toString())
            },
            "stroke_line_join" to { _, view, value ->
                if (view is PathView) view.strokeJoin = parseStrokeJoin(value?.toString())
            },
            "fill_color" to { _, view, value ->
                if (view is PathView) {
                    view.fillColor = if (value == null) 0x00000000 else parseColor(value)
                }
            },
            "stroke_dash_array" to { _, view, value ->
                if (view is PathView) {
                    when (value) {
                        null -> view.dashArray = null
                        is String -> {
                            if (value == "full") {
                                view.requestDashFull()
                            } else {
                                view.clearDash()
                            }
                        }
                        is JSONArray -> {
                            if (value.length() == 0) {
                                view.clearDash()
                            } else {
                                val arr = FloatArray(value.length())
                                for (i in 0 until value.length()) {
                                    arr[i] = value.optDouble(i, 0.0).toFloat()
                                }
                                view.applyDashArray(arr)
                            }
                        }
                        else -> view.clearDash()
                    }
                }
            },
            "stroke_dash_offset" to { _, view, value ->
                if (view is PathView) {
                    view.dashOffset = if (value == null) 0f else toFloat(value, 0f)
                }
            },
        ),
    ))

    // Canvas → Custom CanvasView that renders a declarative display list.
    registry.register(ElementSpec(
        kind = "Canvas",
        create = { CanvasView(it.context) },
        props = mapOf(
            "draw" to { _, view, value ->
                if (view is CanvasView) {
                    view.ops = if (value == null) JSONArray() else value as? JSONArray ?: JSONArray()
                }
            },
            "view_box" to { _, view, value ->
                if (view is CanvasView) {
                    view.viewBox = if (value == null) null else parseViewBox(value)
                }
            },
        ),
    ))
}

private fun parseViewBox(value: Any?): RectF? {
    val array = value as? JSONArray ?: return null
    if (array.length() < 4) return null
    val left = array.optDouble(0, 0.0).toFloat()
    val top = array.optDouble(1, 0.0).toFloat()
    val width = array.optDouble(2, 0.0).toFloat()
    val height = array.optDouble(3, 0.0).toFloat()
    if (width <= 0f || height <= 0f) return null
    return RectF(left, top, left + width, top + height)
}

internal fun updateLinearLayoutGravity(view: LinearLayout) {
    val rounded = view as? RoundedLinearLayout
    val alignItems = rounded?.alignItems
    val justifyContent = rounded?.justifyContent

    val horizontalGravity: Int
    val verticalGravity: Int
    if (view.orientation == LinearLayout.HORIZONTAL) {
        horizontalGravity = axisGravity(justifyContent, horizontal = true)
        verticalGravity = axisGravity(alignItems, horizontal = false)
    } else {
        horizontalGravity = axisGravity(alignItems, horizontal = true)
        verticalGravity = axisGravity(justifyContent, horizontal = false)
    }

    view.gravity = horizontalGravity or verticalGravity
}

private fun axisGravity(value: String?, horizontal: Boolean): Int {
    val normalized = value?.trim()?.lowercase()
    return if (horizontal) {
        when (normalized) {
            "center" -> Gravity.CENTER_HORIZONTAL
            "end", "flex_end", "flex-end" -> Gravity.END
            else -> Gravity.START
        }
    } else {
        when (normalized) {
            "center" -> Gravity.CENTER_VERTICAL
            "end", "flex_end", "flex-end", "bottom" -> Gravity.BOTTOM
            else -> Gravity.TOP
        }
    }
}

/**
 * Parse a color value from a Python wire format.
 *
 * Delegates to [decodeColor] for the canonical RGBA→ARGB conversion.
 * Falls back to transparent only for null, not for malformed values.
 */
internal fun parseColor(value: Any?): Int {
    if (value == null) return 0x00000000
    return try {
        decodeColor(value)
    } catch (_: IllegalArgumentException) {
        0x00000000
    }
}


internal fun toSp(value: Any?, default: Float): Float {
    return when (value) {
        is Number -> value.toFloat()
        is String -> value.toFloatOrNull() ?: default
        else -> default
    }
}

internal fun toFloat(value: Any?, default: Float): Float = toSp(value, default)

// ---------------------------------------------------------------------------
// Typed prop helpers for extension ElementSpecs
// ---------------------------------------------------------------------------

/**
 * Prop handlers: one lambda per prop; a null value means REMOVAL, so each
 * handler applies its default on null. (Python drops explicit nulls before
 * the wire, so null only ever means removal.)
 */
internal fun floatProp(
    default: Float,
    set: (View, Float) -> Unit,
): (PropContext, View, Any?) -> Unit =
    { _, view, value -> set(view, toFloat(value, default)) }

internal fun colorProp(
    default: Int,
    set: (View, Int) -> Unit,
): (PropContext, View, Any?) -> Unit =
    { _, view, value ->
        set(view, if (value == null) default else parseColor(value))
    }

internal fun stringProp(
    default: String,
    set: (View, String) -> Unit,
): (PropContext, View, Any?) -> Unit =
    { _, view, value -> set(view, value?.toString() ?: default) }

internal fun boolProp(
    default: Boolean,
    set: (View, Boolean) -> Unit,
): (PropContext, View, Any?) -> Unit =
    { _, view, value -> set(view, value as? Boolean ?: default) }

internal fun parseStrokeCap(value: String?): Paint.Cap {
    return when (value) {
        "round" -> Paint.Cap.ROUND
        "square" -> Paint.Cap.SQUARE
        else -> Paint.Cap.BUTT
    }
}

internal fun parseStrokeJoin(value: String?): Paint.Join {
    return when (value) {
        "round" -> Paint.Join.ROUND
        "bevel" -> Paint.Join.BEVEL
        else -> Paint.Join.MITER
    }
}

@Suppress("DEPRECATION") // scaledDensity remains the minSdk-safe SP conversion API.
private fun setTextLineHeight(view: TextView, value: Any?) {
    val lineHeightPx = (toSp(value, view.textSize / view.resources.displayMetrics.scaledDensity) *
        view.resources.displayMetrics.scaledDensity).roundToInt()
    val metrics = view.paint.fontMetricsInt
    val currentLineHeight = metrics.descent - metrics.ascent
    view.setLineSpacing((lineHeightPx - currentLineHeight).toFloat(), 1f)
}
