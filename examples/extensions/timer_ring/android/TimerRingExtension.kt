/**
 * TimerRing example extension — native side.
 *
 * Registers the TimerRing ElementSpec exactly like core widgets do. The
 * spec IS the contract: Python queries the frozen registry at startup and
 * builds its validation tables from this registration.
 */
package dev.vyne.ext.timerring

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.view.View
import dev.vyne.ElementRegistry
import dev.vyne.ElementSpec
import dev.vyne.colorProp
import dev.vyne.floatProp

object TimerRingExtension {

    /**
     * Registration entry point called by the generated registrant.
     * `internal` because ElementRegistry is host-internal; extensions
     * compile into the same module, so internal visibility works.
     */
    internal fun register(context: Context, registry: ElementRegistry) {
        registry.register(
            ElementSpec(
                kind = "TimerRing",
                create = { TimerRingView(it.context) },
                props = mapOf(
                    "progress" to floatProp(
                        default = 0f,
                        minimum = 0f,
                        maximum = 1f,
                        read = { view -> (view as TimerRingView).progress },
                        set = { view, v ->
                            (view as TimerRingView).progress = v
                        },
                    ),
                    "ring_color" to colorProp(0xFF6750E8.toInt()) { view, c ->
                        (view as TimerRingView).ringColor = c
                    },
                    "track_color" to colorProp(0xFFE7DEFF.toInt()) { view, c ->
                        (view as TimerRingView).trackColor = c
                    },
                ),
                events = mapOf(
                    "complete" to { view, emit ->
                        val v = view as TimerRingView
                        v.onComplete = {
                            emit(mapOf("finished" to true))
                        }
                        { v.onComplete = null }
                    },
                ),
            ),
        )
    }
}

/**
 * A minimal custom View that draws a circular progress ring.
 * Demonstrates the extension-native side: a View, prop application, and a
 * native event ("complete" when progress reaches 1.0).
 */
class TimerRingView(context: Context) : View(context) {

    var progress: Float = 0f
        set(value) {
            val clamped = value.coerceIn(0f, 1f)
            val changed = field != clamped
            field = clamped
            if (changed) {
                invalidate()
                if (clamped >= 1f) {
                    onComplete?.invoke()
                }
            }
        }

    var ringColor: Int = 0xFF6750E8.toInt()
        set(value) {
            field = value
            invalidate()
        }

    var trackColor: Int = 0xFFE7DEFF.toInt()
        set(value) {
            field = value
            invalidate()
        }

    var onComplete: (() -> Unit)? = null

    private val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
    }

    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val stroke = width.coerceAtMost(height) * 0.12f
        val inset = stroke / 2f + 1f
        val bounds = RectF(inset, inset, width - inset, height - inset)

        trackPaint.strokeWidth = stroke
        trackPaint.color = trackColor
        canvas.drawArc(bounds, 0f, 360f, false, trackPaint)

        ringPaint.strokeWidth = stroke
        ringPaint.color = ringColor
        canvas.drawArc(bounds, -90f, 360f * progress.coerceIn(0f, 1f), false, ringPaint)
    }
}
