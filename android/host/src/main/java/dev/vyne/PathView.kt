package dev.vyne

import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PathMeasure
import android.graphics.RectF
import android.view.View
import org.json.JSONArray
import org.json.JSONObject

/**
 * Custom View that renders pre-validated SVG path commands.
 *
 * Python compiles SVG path strings into a JSON-safe command list.  This View
 * takes that list and draws it using Android's Canvas/Path APIs.  Command
 * interpretation (including relative-to-absolute conversion) is done here,
 * but validation and parsing are done in Python — so the commands arriving
 * here are always well-formed.
 *
 * Scaling: The path is auto-scaled to fit within the View bounds using
 * uniform scale (maintaining aspect ratio), centered both horizontally and
 * vertically.  Stroke width is inversely scaled so it stays the specified
 * visual size regardless of path bounds.
 */
internal class PathView(context: Context) : View(context) {
    // ── Allocation / performance counters (package-visible for tests) ─
    internal var pathBuildCount: Int = 0
        private set
    internal var dashEffectCreateCount: Int = 0
        private set
    internal var drawFrameCount: Int = 0
        private set
    internal var pathMeasureCreateCount: Int = 0
        private set

    var commands: JSONArray = JSONArray()
        set(value) {
            field = value
            rawPath.reset()
            buildPath(value, rawPath)
            rawPath.computeBounds(pathBounds, true)
            // Compute total length across all contours.
            val measure = PathMeasure(rawPath, false)
            pathMeasureCreateCount++
            var totalLength = measure.length
            while (measure.nextContour()) {
                totalLength += measure.length
            }
            pathLength = totalLength
            pathBuildCount++
            // Recompute "full" dash if the path was using it.
            if (usesDashFull) {
                dashArray = if (totalLength > 0f) {
                    floatArrayOf(totalLength, totalLength)
                } else {
                    null
                }
            }
            invalidate()
        }

    var strokeColor: Int = 0xFF000000.toInt()
        set(value) { field = value; invalidate() }
    var strokeWidth: Float = 2f
        set(value) { field = value; invalidate() }
    var strokeCap: Paint.Cap = Paint.Cap.BUTT
        set(value) { field = value; invalidate() }
    var strokeJoin: Paint.Join = Paint.Join.MITER
        set(value) { field = value; invalidate() }
    var fillColor: Int = 0x00000000
        set(value) { field = value; invalidate() }
    var dashArray: FloatArray? = null
        set(value) {
            field = value
            cachedDashEffect = null
            invalidate()
        }
    var dashOffset: Float = 0f
        set(value) {
            field = value
            cachedDashEffect = null
            invalidate()
        }

    private var cachedDashEffect: DashPathEffect? = null

    private fun getDashEffect(): DashPathEffect? {
        val values = dashArray ?: return null
        if (values.isEmpty()) return null
        val cached = cachedDashEffect
        if (cached != null) return cached
        val effect = DashPathEffect(values, dashOffset)
        cachedDashEffect = effect
        dashEffectCreateCount++
        return effect
    }
    var pathLength: Float = 0f
        private set

    private val rawPath = Path()
    private val pathBounds = RectF()
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
    }
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
    }
    private var usesDashFull = false

    /**
     * Set dash array to [pathLength, pathLength] — creates a "full" stroke
     * effect that looks like a solid line but works with dash offset animation
     * (e.g., a "drawing" effect where the line appears to write itself).
     *
     * The "full" dash is recomputed whenever commands change, ensuring it
     * always reflects the current geometry.
     */
    fun requestDashFull() {
        usesDashFull = true
        if (pathLength > 0f) {
            dashArray = floatArrayOf(pathLength, pathLength)
        }
        // If pathLength is 0, the commands setter will compute it when
        // commands arrive.
    }

    fun applyDashArray(values: FloatArray) {
        usesDashFull = false
        dashArray = values
    }

    fun clearDash() {
        usesDashFull = false
        dashArray = null
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val hasCommands = commands.length() > 0
        val hasStroke = strokeColor.ushr(24) > 0 && strokeWidth > 0f
        val strokePad = if (hasStroke) strokeWidth else 0f

        val desiredW: Int
        val desiredH: Int
        if (hasCommands && (pathBounds.width() > 0f || pathBounds.height() > 0f)) {
            // Compute content size from path bounds + stroke padding.
            val contentW = (pathBounds.width() + strokePad).toInt()
            val contentH = (pathBounds.height() + strokePad).toInt()
            desiredW = maxOf(contentW, suggestedMinimumWidth)
            desiredH = maxOf(contentH, suggestedMinimumHeight)
        } else {
            desiredW = suggestedMinimumWidth
            desiredH = suggestedMinimumHeight
        }
        setMeasuredDimension(
            resolveSize(desiredW, widthMeasureSpec),
            resolveSize(desiredH, heightMeasureSpec),
        )
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        drawFrameCount++
        if (commands.length() == 0) return

        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return

        // Handle degenerate bounds (horizontal/vertical lines, point strokes).
        // When one axis has zero extent, we use the nondegenerate axis for
        // scaling and the stroke contributes its own thickness.
        val boundsW = pathBounds.width()
        val boundsH = pathBounds.height()
        val hasStroke = strokeColor.ushr(24) > 0 && strokeWidth > 0f
        val inset = if (hasStroke) strokeWidth / 2f else 0f

        val scale: Float
        val tx: Float
        val ty: Float
        if (boundsW <= 0f && boundsH <= 0f) {
            // Point-degenerate: center and use stroke width for scale.
            scale = if (hasStroke) (minOf(w, h) / strokeWidth).coerceAtMost(1f) else 1f
            tx = w / 2f - pathBounds.left * scale
            ty = h / 2f - pathBounds.top * scale
        } else if (boundsW <= 0f) {
            // Vertical-only: scale by height.
            val availH = (h - inset * 2).coerceAtLeast(1f)
            scale = availH / boundsH
            tx = w / 2f - pathBounds.left * scale
            ty = (h - boundsH * scale) / 2f - pathBounds.top * scale
        } else if (boundsH <= 0f) {
            // Horizontal-only: scale by width.
            val availW = (w - inset * 2).coerceAtLeast(1f)
            scale = availW / boundsW
            tx = (w - boundsW * scale) / 2f - pathBounds.left * scale
            ty = h / 2f - pathBounds.top * scale
        } else {
            val availW = (w - inset * 2).coerceAtLeast(1f)
            val availH = (h - inset * 2).coerceAtLeast(1f)
            scale = minOf(availW / boundsW, availH / boundsH)
            tx = (w - boundsW * scale) / 2f - pathBounds.left * scale
            ty = (h - boundsH * scale) / 2f - pathBounds.top * scale
        }

        canvas.save()
        canvas.translate(tx, ty)
        canvas.scale(scale, scale)
        if (fillColor.ushr(24) > 0) {
            fillPaint.color = fillColor
            canvas.drawPath(rawPath, fillPaint)
        }
        if (hasStroke) {
            strokePaint.color = strokeColor
            strokePaint.strokeWidth = if (scale > 0f) strokeWidth / scale else strokeWidth
            strokePaint.strokeCap = strokeCap
            strokePaint.strokeJoin = strokeJoin
            strokePaint.pathEffect = getDashEffect()
            canvas.drawPath(rawPath, strokePaint)
        }
        canvas.restore()
    }

    companion object {
        /**
         * Build an Android Path from normalized command dicts.
         *
         * Implements the same SVG subset as Python's path_data.py:
         * M/m (move), L/l (line), C/c (cubic), Q/q (quadratic), Z/z (close).
         * Relative commands offset coordinates by the current cursor position.
         * Python already validated arity, so we trust the values array length.
         */
        fun buildPath(commands: JSONArray, out: Path) {
            var currentX = 0f
            var currentY = 0f
            var startX = 0f
            var startY = 0f

            for (index in 0 until commands.length()) {
                val operation = commands.optJSONObject(index) ?: continue
                val command = operation.optString("cmd")
                val values = operation.optJSONArray("values") ?: JSONArray()
                if (!hasArity(command, values)) continue
                val relative = command.length == 1 && command[0].isLowerCase()
                fun x(offset: Int): Float = values.optDouble(offset).toFloat() + if (relative) currentX else 0f
                fun y(offset: Int): Float = values.optDouble(offset).toFloat() + if (relative) currentY else 0f

                when (command.uppercase()) {
                    "M" -> {
                        currentX = x(0); currentY = y(1)
                        startX = currentX; startY = currentY
                        out.moveTo(currentX, currentY)
                    }
                    "L" -> {
                        currentX = x(0); currentY = y(1)
                        out.lineTo(currentX, currentY)
                    }
                    "C" -> {
                        val x1 = x(0); val y1 = y(1)
                        val x2 = x(2); val y2 = y(3)
                        currentX = x(4); currentY = y(5)
                        out.cubicTo(x1, y1, x2, y2, currentX, currentY)
                    }
                    "Q" -> {
                        val x1 = x(0); val y1 = y(1)
                        currentX = x(2); currentY = y(3)
                        out.quadTo(x1, y1, currentX, currentY)
                    }
                    "Z" -> {
                        out.close()
                        currentX = startX; currentY = startY
                    }
                }
            }
        }

        private fun hasArity(command: String, values: JSONArray): Boolean {
            val expected = when (command.uppercase()) {
                "M", "L" -> 2
                "Q" -> 4
                "C" -> 6
                "Z" -> 0
                else -> return false
            }
            return values.length() == expected
        }
    }
}
