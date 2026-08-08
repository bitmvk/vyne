/**
 * Declarative drawing surface with stable operation identity for animation.
 *
 * Python sends a declarative display list; Kotlin only decodes and paints it.
 * Each operation may carry a ``_vyne_op_id`` stable identifier that the unified
 * ``PresentationEngine`` uses for Canvas animation instead of fragile JSON paths.
 *
 * Animation is delegated to ``PresentationEngine`` — this View no longer contains
 * its own Choreographer loop or spring physics.
 */
package dev.vyne

import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PathMeasure
import android.graphics.RectF
import android.view.View
import android.view.ViewGroup
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.min

internal class CanvasView(context: Context) : View(context) {
    // ── Allocation / performance counters (package-visible for tests) ─
    internal var drawFrameCount: Int = 0
        private set
    internal var dashEffectCreateCount: Int = 0
        private set
    internal var opsPrecompileCount: Int = 0
        private set

    var ops: JSONArray = JSONArray()
        set(value) {
            field = resolveArray(value)
            compileStaticDrawData()
            opsPrecompileCount++
            requestLayout()
            invalidate()
        }

    var viewBox: RectF? = null
        set(value) {
            field = value
            cachedDefaultViewBox = null
            invalidate()
        }

    /** Cached default view box to avoid per-frame RectF allocations. */
    private var cachedDefaultViewBox: RectF? = null

    private fun defaultViewBox(w: Float, h: Float): RectF {
        val cached = cachedDefaultViewBox
        if (cached != null && cached.width() == w && cached.height() == h) {
            return cached
        }
        val vb = RectF(0f, 0f, w, h)
        cachedDefaultViewBox = vb
        return vb
    }

    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
    }
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
    }
    private val tempPath = Path()
    private val trimmedPath = Path()
    private val compiledPaths = mutableMapOf<Int, Path>()
    private val compiledDashEffects = mutableMapOf<Int, DashPathEffect?>()
    private val pathMeasure = PathMeasure()
    private val tempRect = RectF()

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        if (ops.length() == 0) {
            setMeasuredDimension(
                resolveSize(suggestedMinimumWidth, widthMeasureSpec),
                resolveSize(suggestedMinimumHeight, heightMeasureSpec),
            )
            return
        }

        // Compute intrinsic content size from the display list:
        // - If viewBox is set, use viewBox dimensions.
        // - Otherwise, compute the bounding box of all draw ops.
        val contentW: Float
        val contentH: Float
        val vb = viewBox
        if (vb != null && vb.width() > 0f && vb.height() > 0f) {
            contentW = vb.width()
            contentH = vb.height()
        } else {
            val bounds = computeOpsBounds()
            if (bounds != null && bounds.width() > 0f && bounds.height() > 0f) {
                contentW = bounds.width()
                contentH = bounds.height()
            } else {
                // Fallback: minimum visible area.
                contentW = 100f
                contentH = 100f
            }
        }
        val desiredW = maxOf(contentW.toInt(), suggestedMinimumWidth)
        val desiredH = maxOf(contentH.toInt(), suggestedMinimumHeight)
        setMeasuredDimension(
            resolveSize(desiredW, widthMeasureSpec),
            resolveSize(desiredH, heightMeasureSpec),
        )
    }

    /**
     * Compute a bounding rect for all draw ops in the current display list.
     * Returns null if the bounding rect cannot be computed or is degenerate.
     */
    private fun computeOpsBounds(): RectF? {
        var minX = Float.MAX_VALUE
        var minY = Float.MAX_VALUE
        var maxX = Float.MIN_VALUE
        var maxY = Float.MIN_VALUE
        var found = false

        for (i in 0 until ops.length()) {
            val op = ops.optJSONObject(i) ?: continue
            val opRect = when (op.optString("kind")) {
                "rect", "round_rect" -> {
                    val x = op.optDouble("x", 0.0).toFloat()
                    val y = op.optDouble("y", 0.0).toFloat()
                    val w = op.optDouble("width", 0.0).toFloat()
                    val h = op.optDouble("height", 0.0).toFloat()
                    if (w > 0f && h > 0f) RectF(x, y, x + w, y + h) else null
                }
                "circle" -> {
                    val cx = op.optDouble("cx", 0.0).toFloat()
                    val cy = op.optDouble("cy", 0.0).toFloat()
                    val r = op.optDouble("r", 0.0).toFloat()
                    if (r > 0f) RectF(cx - r, cy - r, cx + r, cy + r) else null
                }
                "line" -> {
                    val x1 = op.optDouble("x1", 0.0).toFloat()
                    val y1 = op.optDouble("y1", 0.0).toFloat()
                    val x2 = op.optDouble("x2", 0.0).toFloat()
                    val y2 = op.optDouble("y2", 0.0).toFloat()
                    RectF(minOf(x1, x2), minOf(y1, y2), maxOf(x1, x2), maxOf(y1, y2))
                }
                "path" -> {
                    // Path ops: try to compute bounds from commands.
                    computePathBounds(op.optJSONArray("commands"))
                }
                else -> null
            }
            if (opRect != null) {
                minX = minOf(minX, opRect.left)
                minY = minOf(minY, opRect.top)
                maxX = maxOf(maxX, opRect.right)
                maxY = maxOf(maxY, opRect.bottom)
                found = true
            }
        }
        return if (found) RectF(minX, minY, maxX, maxY) else null
    }

    /**
     * Compute the bounding rect of a path command sequence.
     */
    private fun computePathBounds(commands: JSONArray?): RectF? {
        if (commands == null || commands.length() == 0) return null
        tempPath.reset()
        PathView.buildPath(commands, tempPath)
        tempPath.computeBounds(tempRect, true)
        return if (tempRect.width() > 0f || tempRect.height() > 0f) RectF(tempRect) else null
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        drawFrameCount++
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return

        // View box scaling: similar to SVG viewBox — maps a logical coordinate
        // space to the available pixel area using uniform scale + center.
        val vb = viewBox ?: defaultViewBox(w, h)
        if (vb.width() <= 0f || vb.height() <= 0f) return
        val scale = min(w / vb.width(), h / vb.height())
        val tx = (w - vb.width() * scale) / 2f - vb.left * scale
        val ty = (h - vb.height() * scale) / 2f - vb.top * scale

        canvas.save()
        canvas.translate(tx, ty)
        canvas.scale(scale, scale)
        for (i in 0 until ops.length()) {
            val op = ops.optJSONObject(i) ?: continue
            when (op.optString("kind")) {
                "rect" -> drawRect(canvas, op, i, rounded = false)
                "round_rect" -> drawRect(canvas, op, i, rounded = true)
                "circle" -> drawCircle(canvas, op, i)
                "line" -> drawLine(canvas, op, i)
                "path" -> drawPath(canvas, op, i)
            }
        }
        canvas.restore()
    }

    // ── Stable operation ID field access ────────────────────────────

    /**
     * Read a numeric field from a Canvas operation identified by op_id.
     *
     * The field is a canonical Canvas numeric field such as "x",
     * "stroke_width", or "opacity".
     * Returns 0f if the operation or field is not found.
     */
    fun readOpField(opId: String, field: String): Float {
        val (op, _) = findOp(opId) ?: return 0f
        return readNestedField(op, field)
    }

    fun hasOpField(opId: String, field: String): Boolean {
        val (op, _) = findOp(opId) ?: return false
        return op.opt(field) is Number
    }

    /**
     * Write a numeric value to a Canvas operation field identified by op_id.
     * Triggers an invalidate so the change is visible on the next frame.
     */
    fun writeOpField(opId: String, field: String, value: Float) {
        val (op, index) = findOp(opId) ?: return
        writeNestedField(op, field, value.toDouble())
        if (field == "dash_offset") {
            compileDashEffect(index, op)
        }
        if (affectsWrappedIntrinsicSize(field)) {
            requestLayout()
        }
        invalidate()
    }

    private fun affectsWrappedIntrinsicSize(field: String): Boolean {
        val params = layoutParams ?: return field in INTRINSIC_SIZE_FIELDS
        return (
            params.width == ViewGroup.LayoutParams.WRAP_CONTENT &&
                field in INTRINSIC_WIDTH_FIELDS
        ) || (
            params.height == ViewGroup.LayoutParams.WRAP_CONTENT &&
                field in INTRINSIC_HEIGHT_FIELDS
        )
    }

    private fun findOp(opId: String): Pair<JSONObject, Int>? {
        for (i in 0 until ops.length()) {
            val op = ops.optJSONObject(i) ?: continue
            if (op.optString(CanvasOpIdentity.RESERVED_ID_KEY) == opId) {
                return op to i
            }
        }
        return null
    }

    /** Read a field path like "fill.alpha" or just "x" from a JSONObject. */
    private fun readNestedField(op: JSONObject, field: String): Float {
        val parts = field.split(".")
        var current: Any? = op
        for (part in parts.dropLast(1)) {
            current = (current as? JSONObject)?.opt(part) ?: return 0f
        }
        val leaf = parts.last()
        return when (val value = (current as? JSONObject)?.opt(leaf)) {
            is Number -> value.toFloat()
            is String -> value.toFloatOrNull() ?: 0f
            else -> 0f
        }
    }

    /** Write a field path in a JSONObject. Creates nested objects as needed. */
    private fun writeNestedField(op: JSONObject, field: String, value: Double) {
        val parts = field.split(".")
        var current: JSONObject = op
        for (part in parts.dropLast(1)) {
            val next = current.optJSONObject(part)
            if (next != null) {
                current = next
            } else {
                val created = JSONObject()
                current.put(part, created)
                current = created
            }
        }
        current.put(parts.last(), value)
    }

    /**
     * Resolve AnimatedValue markers in the incoming ops, replacing them
     * with their initial static values.  The actual animation is driven
     * by the PresentationEngine via ``motion_set_target`` ops sent
     * alongside the commit.
     */
    fun resolveAnimatedValues(incoming: JSONArray): JSONArray {
        return resolveArray(incoming)
    }

    private fun resolveArray(array: JSONArray): JSONArray = JSONArray().also { result ->
        for (i in 0 until array.length()) {
            result.put(resolveValue(array.opt(i)))
        }
    }

    private fun resolveObject(obj: JSONObject): Any {
        // Animated marker → extract the static initial value.
        if (
            obj.optBoolean(ANIMATED_VALUE_MARKER, false) ||
                obj.optBoolean(ANIMATED_NODE_MARKER, false)
        ) {
            return obj.optDouble("value", 0.0)
        }
        return JSONObject().also { result ->
            val keys = obj.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                result.put(key, resolveValue(obj.opt(key)))
            }
        }
    }

    private fun resolveValue(value: Any?): Any? = when (value) {
        is JSONObject -> resolveObject(value)
        is JSONArray -> resolveArray(value)
        else -> value
    }

    // ── Drawing helpers ─────────────────────────────────────────────

    private fun drawRect(canvas: Canvas, op: JSONObject, index: Int, rounded: Boolean) {
        val x = floatProp(op, "x")
        val y = floatProp(op, "y")
        val width = floatProp(op, "width")
        val height = floatProp(op, "height")
        if (width <= 0f || height <= 0f) return
        tempRect.set(x, y, x + width, y + height)
        val radius = floatProp(op, "radius")

        paintFill(op)?.let { paint ->
            if (rounded || radius > 0f) {
                canvas.drawRoundRect(tempRect, radius, radius, paint)
            } else {
                canvas.drawRect(tempRect, paint)
            }
        }
        paintStroke(op, index)?.let { paint ->
            if (rounded || radius > 0f) {
                canvas.drawRoundRect(tempRect, radius, radius, paint)
            } else {
                canvas.drawRect(tempRect, paint)
            }
        }
    }

    private fun drawCircle(canvas: Canvas, op: JSONObject, index: Int) {
        val cx = floatProp(op, "cx")
        val cy = floatProp(op, "cy")
        val r = floatProp(op, "r")
        if (r <= 0f) return
        paintFill(op)?.let { canvas.drawCircle(cx, cy, r, it) }
        paintStroke(op, index)?.let { canvas.drawCircle(cx, cy, r, it) }
    }

    private fun drawLine(canvas: Canvas, op: JSONObject, index: Int) {
        val paint = paintStroke(op, index) ?: return
        canvas.drawLine(
            floatProp(op, "x1"),
            floatProp(op, "y1"),
            floatProp(op, "x2"),
            floatProp(op, "y2"),
            paint,
        )
    }

    /**
     * Draw a path inside a Canvas operation.
     *
     * Supports numeric "trim_start" and "trim_end" properties, including
     * declarative AnimatedValue targets resolved by the presentation engine.
     *
     * Trim iterates ALL contours.  The concatenated length across all
     * contours is used for the trim range, matching the documented
     * multi-contour trim semantics.
     */
    private fun drawPath(canvas: Canvas, op: JSONObject, index: Int) {
        val sourcePath = compiledPaths[index] ?: return

        val pathToDraw = if (op.has("trim_start") || op.has("trim_end")) {
            val start = floatProp(op, "trim_start", 0f).coerceIn(0f, 1f)
            val end = floatProp(op, "trim_end", 1f).coerceIn(0f, 1f)

            // Compute total concatenated length across all contours.
            val totalLength = computeTotalLength(sourcePath, pathMeasure)
            val absoluteStart = totalLength * start
            val absoluteEnd = totalLength * end

            trimmedPath.reset()
            pathMeasure.setPath(sourcePath, false)
            var accumulator = 0f
            var remaining = absoluteStart
            while (true) {
                val contourLength = pathMeasure.length
                if (contourLength > 0f) {
                    val segmentStart = (remaining / contourLength).coerceIn(0f, 1f)
                    val contourEndDist = (absoluteEnd - accumulator).coerceAtMost(contourLength)
                    val segmentEnd = (contourEndDist / contourLength).coerceIn(segmentStart, 1f)
                    if (segmentEnd > segmentStart) {
                        pathMeasure.getSegment(
                            contourLength * segmentStart,
                            contourLength * segmentEnd,
                            trimmedPath,
                            true,
                        )
                        if (accumulator + contourLength >= absoluteEnd) break
                    }
                    accumulator += contourLength
                    remaining = (absoluteStart - accumulator).coerceAtLeast(0f)
                }
                if (!pathMeasure.nextContour()) break
            }
            trimmedPath
        } else {
            sourcePath
        }

        paintFill(op)?.let { canvas.drawPath(pathToDraw, it) }
        paintStroke(op, index)?.let { canvas.drawPath(pathToDraw, it) }
    }

    private fun paintFill(op: JSONObject): Paint? {
        if (!op.has("fill")) return null
        val color = parseColor(op.opt("fill"))
        if (color.ushr(24) == 0) return null
        fillPaint.color = color
        fillPaint.alpha = scaledAlpha(color, floatProp(op, "opacity", 1f))
        return fillPaint
    }

    private fun paintStroke(op: JSONObject, index: Int): Paint? {
        if (!op.has("stroke")) return null
        val color = parseColor(op.opt("stroke"))
        val strokeWidth = floatProp(op, "stroke_width", 1f)
        if (color.ushr(24) == 0 || strokeWidth <= 0f) return null
        strokePaint.color = color
        strokePaint.alpha = scaledAlpha(color, floatProp(op, "opacity", 1f))
        strokePaint.strokeWidth = strokeWidth
        strokePaint.strokeCap = parseStrokeCap(op.optString("stroke_cap"))
        strokePaint.strokeJoin = parseStrokeJoin(op.optString("stroke_join"))
        strokePaint.pathEffect = compiledDashEffects[index]
        return strokePaint
    }

    /** Compile all immutable, non-animation draw objects when ops change. */
    private fun compileStaticDrawData() {
        compiledPaths.clear()
        compiledDashEffects.clear()
        for (index in 0 until ops.length()) {
            val op = ops.optJSONObject(index) ?: continue
            if (op.optString("kind") == "path") {
                val commands = op.optJSONArray("commands")
                if (commands != null) {
                    compiledPaths[index] = Path().also {
                        PathView.buildPath(commands, it)
                    }
                }
            }
            compileDashEffect(index, op)
        }
    }

    private fun compileDashEffect(index: Int, op: JSONObject) {
        val dash = op.optJSONArray("dash")
        if (dash == null || dash.length() == 0) {
            compiledDashEffects[index] = null
            return
        }
        val values = FloatArray(dash.length())
        for (i in 0 until dash.length()) {
            values[i] = dash.getDouble(i).toFloat()
        }
        compiledDashEffects[index] =
            DashPathEffect(
                values,
                op.optDouble("dash_offset", 0.0).toFloat(),
            )
        dashEffectCreateCount++
    }

    private fun scaledAlpha(color: Int, alpha: Float): Int {
        val base = color.ushr(24)
        return (base * alpha.coerceIn(0f, 1f)).toInt().coerceIn(0, 255)
    }

    /** Extract a required float property from a JSONObject, defaulting to 0. */
    private fun floatProp(op: JSONObject, name: String): Float =
        op.optDouble(name, 0.0).toFloat()

    /** Extract an optional float property with an explicit default. */
    private fun floatProp(op: JSONObject, name: String, default: Float): Float =
        op.optDouble(name, default.toDouble()).toFloat()

    companion object {
        const val ANIMATED_VALUE_MARKER = "__vyne_animated_value__"
        const val ANIMATED_NODE_MARKER = "__vyne_animated_node__"
        private val INTRINSIC_WIDTH_FIELDS =
            setOf(
                "x", "width", "cx", "r", "x1", "x2",
            )
        private val INTRINSIC_HEIGHT_FIELDS =
            setOf(
                "y", "height", "cy", "r", "y1", "y2",
            )
        private val INTRINSIC_SIZE_FIELDS =
            INTRINSIC_WIDTH_FIELDS + INTRINSIC_HEIGHT_FIELDS

        /**
         * Compute the total concatenated length of all contours in a path.
         *
         * Iterates all contours via [PathMeasure.nextContour], summing each
         * contour's length.  This is used for multi-contour trim calculations.
         */
        internal fun computeTotalLength(path: Path, measure: PathMeasure): Float {
            measure.setPath(path, false)
            var total = measure.length
            while (measure.nextContour()) {
                total += measure.length
            }
            return total
        }
    }
}

/** Stable operation identity keys — mirrored from Python motion.py. */
internal object CanvasOpIdentity {
    const val RESERVED_ID_KEY = "_vyne_op_id"
}
