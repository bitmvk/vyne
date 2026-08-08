/**
 * Pure pointer session state machine for Android touch arbitration.
 *
 * This is a deterministic reducer over pointer events.  The Renderer owns
 * View mutation and event emission; PointerSession only produces the
 * state transitions and action decisions needed to implement synchronous
 * gesture arbitration, tap qualification, and parent-scroll coexistence.
 *
 * States:
 *   Idle        — no active pointer
 *   PendingAxis — down received with axis capture; waiting for slop to decide
 *   Captured    — axis claimed; tracking pointer events
 *   Rejected    — axis rejected; parent scroll owns the gesture
 *   Ended       — pointer up after a completed gesture
 *   Cancelled   — system or parent cancelled
 *
 * The session preserves the original DOWN event payload so that
 * gesture-handoff events (emitted late-down on tap) carry the correct
 * pointer ID, pressure, time, and coordinates.
 */
package dev.vyne

import android.annotation.SuppressLint
import android.os.Build
import android.view.MotionEvent

/**
 * Pure-data pointer event used by the reducer.  Extracted from MotionEvent
 * in the Renderer so the reducer can be unit-tested without Android stubs.
 */
data class PointerEvent(
    val action: Int,
    val pointerId: Int,
    val actionIndex: Int,
    val pointerCount: Int,
    val x: Float,
    val y: Float,
    val rawX: Float,
    val rawY: Float,
    val downTime: Long,
    val eventTime: Long,
    val pressure: Float,
    val size: Float,
    val toolType: Int,
    val source: Int,
) {
    companion object {
        @SuppressLint("NewApi")
        fun fromMotionEvent(event: MotionEvent): PointerEvent {
            val index = event.actionIndex
            return PointerEvent(
                action = event.actionMasked,
                pointerId = event.getPointerId(index),
                actionIndex = index,
                pointerCount = event.pointerCount,
                x = event.getX(index),
                y = event.getY(index),
                rawX = getRawXCompat(event, index),
                rawY = getRawYCompat(event, index),
                downTime = event.downTime,
                eventTime = event.eventTime,
                pressure = event.getPressure(index),
                size = event.getSize(index),
                toolType = event.getToolType(index),
                source = event.source,
            )
        }

        /** Find the pointer index for a pointer ID in a MotionEvent. */
        fun findPointerIndex(event: MotionEvent, pointerId: Int): Int =
            event.findPointerIndex(pointerId).takeIf { it >= 0 } ?: -1

        /** Extract data for a specific pointer index. */
        @SuppressLint("NewApi")
        fun fromMotionEventAt(event: MotionEvent, pointerIndex: Int): PointerEvent? {
            if (pointerIndex < 0 || pointerIndex >= event.pointerCount) return null
            return PointerEvent(
                action = event.actionMasked,
                pointerId = event.getPointerId(pointerIndex),
                actionIndex = event.actionIndex,
                pointerCount = event.pointerCount,
                x = event.getX(pointerIndex),
                y = event.getY(pointerIndex),
                rawX = getRawXCompat(event, pointerIndex),
                rawY = getRawYCompat(event, pointerIndex),
                downTime = event.downTime,
                eventTime = event.eventTime,
                pressure = event.getPressure(pointerIndex),
                size = event.getSize(pointerIndex),
                toolType = event.getToolType(pointerIndex),
                source = event.source,
            )
        }

        /**
         * Compatibility wrapper: getRawX(int) requires API 29.
         * Fall back to getRawX() (API 14) on earlier releases.
         */
        private fun getRawXCompat(event: MotionEvent, pointerIndex: Int): Float {
            return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                event.getRawX(pointerIndex)
            } else {
                event.rawX
            }
        }

        private fun getRawYCompat(event: MotionEvent, pointerIndex: Int): Float {
            return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                event.getRawY(pointerIndex)
            } else {
                event.rawY
            }
        }
    }
}

/**
 * Pointer session configuration provided by the host View.
 */
data class PointerSessionConfig(
    val touchSlop: Float,
    val captureAxis: String?,         // "horizontal", "vertical", or null (no axis preference)
    val hasPointerDown: Boolean,       // true if a pointer_down handler is registered
    val hasPointerMove: Boolean,
    val hasPointerUp: Boolean,
    val hasPointerCancel: Boolean,
    val gestureId: Long,
)

/**
 * The decision the reducer makes for the host Renderer.
 */
sealed class PointerDecision {
    /** Do nothing; continue tracking. */
    data object Noop : PointerDecision()

    /** Emit the named pointer event from this immutable decision-time sample. */
    data class EmitPointerEvent(
        val eventName: String,
        val sample: PointerSessionState,
    ) : PointerDecision()

    /** Request the parent to disallow/allow touch interception. */
    data class ParentIntercept(val disallow: Boolean) : PointerDecision()

    /** The tap qualifies; call performClick() on the target View. */
    data object PerformClick : PointerDecision()

    /** Reset the session (clear active pointer/gesture/axis state). */
    data object Reset : PointerDecision()
}

/**
 * Immutable snapshot of the current pointer session state.
 */
data class PointerSessionState(
    val phase: PointerPhase,
    val activePointerId: Int?,
    val gestureId: Long?,
    val axisClaimed: Boolean?,        // null = pending, true = captured, false = rejected
    val downEmitted: Boolean,
    val downTime: Long,
    val downEventTime: Long,
    val downX: Float,
    val downY: Float,
    val downRawX: Float,
    val downRawY: Float,
    val downPressure: Float,
    val downSize: Float,
    val downToolType: Int,
    val downSource: Int,
    val lastX: Float,
    val lastY: Float,
    val lastEventTime: Long,
    val lastPressure: Float,
    val lastSize: Float,
    val lastToolType: Int,
    val lastSource: Int,
) {
    companion object {
        val IDLE = PointerSessionState(
            phase = PointerPhase.Idle,
            activePointerId = null,
            gestureId = null,
            axisClaimed = null,
            downEmitted = false,
            downTime = 0L,
            downEventTime = 0L,
            downX = 0f,
            downY = 0f,
            downRawX = 0f,
            downRawY = 0f,
            downPressure = 1f,
            downSize = 0f,
            downToolType = MotionEvent.TOOL_TYPE_UNKNOWN,
            downSource = 0,
            lastX = 0f,
            lastY = 0f,
            lastEventTime = 0L,
            lastPressure = 1f,
            lastSize = 0f,
            lastToolType = MotionEvent.TOOL_TYPE_UNKNOWN,
            lastSource = 0,
        )
    }
}

enum class PointerPhase {
    Idle,
    PendingAxis,
    Captured,
    Rejected,
    Ended,
    Cancelled,
    Suppressed,
}

/**
 * The result of reducing a PointerEvent through the session.
 */
data class PointerTransition(
    val state: PointerSessionState,
    val decisions: List<PointerDecision>,
)

/**
 * Pure reducer: (current state, pointer event, config) -> next state + decisions.
 *
 * All Android-specific View operations happen in the Renderer after calling
 * this reducer.  The reducer itself is independently unit-testable because
 * it operates on plain data classes.
 */
object PointerSession {

    fun reduce(
        state: PointerSessionState,
        event: PointerEvent,
        config: PointerSessionConfig,
    ): PointerTransition {
        return when (event.action) {
            MotionEvent.ACTION_DOWN -> handleDown(state, event, config)
            MotionEvent.ACTION_MOVE -> handleMove(state, event, config)
            MotionEvent.ACTION_UP -> handleUp(state, event, config)
            MotionEvent.ACTION_POINTER_DOWN -> handlePointerDown(state, event, config)
            MotionEvent.ACTION_POINTER_UP -> handlePointerUp(state, event, config)
            MotionEvent.ACTION_CANCEL -> handleCancel(state, event, config)
            else -> PointerTransition(state, listOf(PointerDecision.Noop))
        }
    }

    private fun handleDown(
        state: PointerSessionState,
        event: PointerEvent,
        config: PointerSessionConfig,
    ): PointerTransition {
        val hasAxisCapture = config.captureAxis != null
        val decisions = mutableListOf<PointerDecision>()

        val nextPhase = if (hasAxisCapture) PointerPhase.PendingAxis else PointerPhase.Captured
        val axisClaimed: Boolean? = null

        if (hasAxisCapture) {
            decisions.add(PointerDecision.ParentIntercept(disallow = true))
        }

        val nextState = PointerSessionState(
            phase = nextPhase,
            activePointerId = event.pointerId,
            gestureId = config.gestureId,
            axisClaimed = axisClaimed,
            downEmitted = !hasAxisCapture && config.hasPointerDown,
            downTime = event.downTime,
            downEventTime = event.eventTime,
            downX = event.x,
            downY = event.y,
            downRawX = event.rawX,
            downRawY = event.rawY,
            downPressure = event.pressure,
            downSize = event.size,
            downToolType = event.toolType,
            downSource = event.source,
            lastX = event.x,
            lastY = event.y,
            lastEventTime = event.eventTime,
            lastPressure = event.pressure,
            lastSize = event.size,
            lastToolType = event.toolType,
            lastSource = event.source,
        )
        if (!hasAxisCapture && config.hasPointerDown) {
            decisions.add(PointerDecision.EmitPointerEvent("pointer_down", nextState))
        }

        return PointerTransition(nextState, decisions)
    }

    private fun handleMove(
        state: PointerSessionState,
        event: PointerEvent,
        config: PointerSessionConfig,
    ): PointerTransition {
        if (state.phase != PointerPhase.PendingAxis &&
            state.phase != PointerPhase.Captured
        ) {
            return PointerTransition(state, listOf(PointerDecision.Noop))
        }

        val deltaX = event.x - state.downX
        val deltaY = event.y - state.downY
        val decisions = mutableListOf<PointerDecision>()

        if (state.phase == PointerPhase.PendingAxis && state.axisClaimed == null) {
            val resolvedAxis = resolveAxis(deltaX, deltaY, config.touchSlop)
            if (resolvedAxis != null) {
                if (resolvedAxis == config.captureAxis) {
                    val nextState = state.withCurrent(event).copy(
                        phase = PointerPhase.Captured,
                        axisClaimed = true,
                    )
                    decisions.add(PointerDecision.ParentIntercept(disallow = true))
                    if (!state.downEmitted && config.hasPointerDown) {
                        decisions.add(PointerDecision.EmitPointerEvent(
                            "pointer_down", state.downSample()
                        ))
                    }
                    if (config.hasPointerMove) {
                        decisions.add(PointerDecision.EmitPointerEvent("pointer_move", nextState))
                    }
                    return PointerTransition(nextState, decisions)
                } else {
                    val nextState = state.withCurrent(event).copy(
                        phase = PointerPhase.Rejected,
                        axisClaimed = false,
                    )
                    decisions.add(PointerDecision.ParentIntercept(disallow = false))
                    if (config.hasPointerCancel) {
                        decisions.add(PointerDecision.EmitPointerEvent("pointer_cancel", nextState))
                    }
                    return PointerTransition(nextState, decisions)
                }
            }
            return PointerTransition(state, listOf(PointerDecision.Noop))
        }

        val nextState = state.withCurrent(event)
        if (state.phase == PointerPhase.Captured && config.hasPointerMove) {
            decisions.add(PointerDecision.EmitPointerEvent("pointer_move", nextState))
        }
        return PointerTransition(nextState, decisions)
    }

    private fun handleUp(
        state: PointerSessionState,
        event: PointerEvent,
        config: PointerSessionConfig,
    ): PointerTransition {
        if (state.phase == PointerPhase.Suppressed) {
            return PointerTransition(
                PointerSessionState.IDLE,
                listOf(PointerDecision.Reset),
            )
        }
        val sample = state.withCurrent(event)
        val decisions = mutableListOf<PointerDecision>()

        when (state.phase) {
            PointerPhase.PendingAxis -> {
                if (!state.downEmitted && config.hasPointerDown) {
                    decisions.add(PointerDecision.EmitPointerEvent(
                        "pointer_down", state.downSample()
                    ))
                }
                if (config.hasPointerUp) {
                    decisions.add(PointerDecision.EmitPointerEvent("pointer_up", sample))
                }
                decisions.add(PointerDecision.PerformClick)
            }
            PointerPhase.Captured -> {
                if (config.hasPointerUp) {
                    decisions.add(PointerDecision.EmitPointerEvent("pointer_up", sample))
                }
                val deltaX = event.x - state.downX
                val deltaY = event.y - state.downY
                val slopSq = config.touchSlop * config.touchSlop
                if (deltaX * deltaX + deltaY * deltaY <= slopSq) {
                    decisions.add(PointerDecision.PerformClick)
                }
            }
            PointerPhase.Rejected -> { /* parent owns it */ }
            else -> return PointerTransition(state, decisions)
        }

        decisions.add(PointerDecision.ParentIntercept(disallow = false))
        decisions.add(PointerDecision.Reset)
        return PointerTransition(sample.copy(phase = PointerPhase.Ended), decisions)
    }

    private fun handlePointerDown(
        state: PointerSessionState,
        event: PointerEvent,
        config: PointerSessionConfig,
    ): PointerTransition {
        if (state.phase !in setOf(PointerPhase.PendingAxis, PointerPhase.Captured)) {
            return PointerTransition(state, listOf(PointerDecision.Noop))
        }
        val sample = state.withCurrent(event)
        val decisions = mutableListOf<PointerDecision>()
        if (config.hasPointerCancel) {
            decisions.add(PointerDecision.EmitPointerEvent("pointer_cancel", sample))
        }
        decisions.add(PointerDecision.ParentIntercept(disallow = false))
        // Keep a suppression marker until the final ACTION_UP.  A secondary
        // pointer never replaces framework gesture ownership implicitly.
        return PointerTransition(sample.copy(phase = PointerPhase.Suppressed), decisions)
    }

    private fun handlePointerUp(
        state: PointerSessionState,
        event: PointerEvent,
        config: PointerSessionConfig,
    ): PointerTransition {
        if (state.phase == PointerPhase.Suppressed) {
            return PointerTransition(state, listOf(PointerDecision.Noop))
        }
        if (event.pointerId != state.activePointerId) {
            return PointerTransition(state, listOf(PointerDecision.Noop))
        }
        val sample = state.withCurrent(event)
        val decisions = mutableListOf<PointerDecision>()
        if (state.phase == PointerPhase.Captured && config.hasPointerUp) {
            decisions.add(PointerDecision.EmitPointerEvent("pointer_up", sample))
        }
        decisions.add(PointerDecision.ParentIntercept(disallow = false))
        decisions.add(PointerDecision.Reset)
        return PointerTransition(sample.copy(phase = PointerPhase.Ended), decisions)
    }

    private fun handleCancel(
        state: PointerSessionState,
        event: PointerEvent,
        config: PointerSessionConfig,
    ): PointerTransition {
        if (state.phase == PointerPhase.Idle) {
            return PointerTransition(state, listOf(PointerDecision.Noop))
        }
        val sample = state.withCurrent(event)
        val decisions = mutableListOf<PointerDecision>()
        if (state.phase in setOf(PointerPhase.Captured, PointerPhase.PendingAxis) &&
            config.hasPointerCancel
        ) {
            decisions.add(PointerDecision.EmitPointerEvent("pointer_cancel", sample))
        }
        if (state.phase != PointerPhase.Suppressed) {
            decisions.add(PointerDecision.ParentIntercept(disallow = false))
        }
        decisions.add(PointerDecision.Reset)
        return PointerTransition(sample.copy(phase = PointerPhase.Cancelled), decisions)
    }

    private fun PointerSessionState.withCurrent(event: PointerEvent): PointerSessionState = copy(
        lastX = event.x,
        lastY = event.y,
        lastEventTime = event.eventTime,
        lastPressure = event.pressure,
        lastSize = event.size,
        lastToolType = event.toolType,
        lastSource = event.source,
    )

    private fun PointerSessionState.downSample(): PointerSessionState = copy(
        lastX = downX,
        lastY = downY,
        lastEventTime = downEventTime,
        lastPressure = downPressure,
        lastSize = downSize,
        lastToolType = downToolType,
        lastSource = downSource,
    )

    /**
     * Resolve the dominant movement axis once the slop threshold is exceeded.
     *
     * Returns "horizontal", "vertical", or null if still within slop.
     */
    internal fun resolveAxis(deltaX: Float, deltaY: Float, touchSlop: Float): String? {
        val slopSq = touchSlop * touchSlop
        if (deltaX * deltaX + deltaY * deltaY <= slopSq) return null
        return if (kotlin.math.abs(deltaX) >= kotlin.math.abs(deltaY)) {
            "horizontal"
        } else {
            "vertical"
        }
    }
}

/**
 * Host-side extension: reduce a MotionEvent through PointerSession.
 *
 * Finds the active pointer index (falling back to actionIndex when the
 * pointer ID is not found) and delegates to the pure reducer.
 */
fun PointerSession.reduceMotionEvent(
    state: PointerSessionState,
    event: MotionEvent,
    activePointerId: Int?,
    config: PointerSessionConfig,
): PointerTransition {
    val pointerEvent: PointerEvent = if (activePointerId != null) {
        val idx = PointerEvent.findPointerIndex(event, activePointerId)
        if (idx >= 0) {
            PointerEvent.fromMotionEventAt(event, idx)!!
        } else {
            PointerEvent.fromMotionEvent(event)
        }
    } else {
        PointerEvent.fromMotionEvent(event)
    }
    return PointerSession.reduce(state, pointerEvent, config)
}
