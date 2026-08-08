/**
 * Native-owned animation presentation engine.
 *
 * Commits are only the ordered control plane. Once a target is accepted this
 * engine owns every presentation frame, independently of Python and commit
 * timing. View and Canvas properties share the same clock, tween equations,
 * spring integration, retargeting, keyframe, cancellation, and lifecycle
 * behavior.
 */
package dev.vyne

import android.view.Choreographer
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

internal interface AnimationFrameClock {
    val frameIntervalMillis: Long
    fun postFrame(callback: (Long) -> Unit)
    fun cancelFrame()
}

private class ChoreographerAnimationFrameClock : AnimationFrameClock {
    private var posted: Choreographer.FrameCallback? = null

    override val frameIntervalMillis: Long
        get() = 16L

    override fun postFrame(callback: (Long) -> Unit) {
        val frame = Choreographer.FrameCallback { frameTimeNanos ->
            posted = null
            callback(frameTimeNanos)
        }
        posted = frame
        Choreographer.getInstance().postFrameCallback(frame)
    }

    override fun cancelFrame() {
        posted?.let { Choreographer.getInstance().removeFrameCallback(it) }
        posted = null
    }
}

internal class PresentationEngine(
    private val frameClock: AnimationFrameClock =
        ChoreographerAnimationFrameClock(),
    private val nowNanos: () -> Long = System::nanoTime,
    private val lifecycleSink: (Lifecycle) -> Unit = {},
) {
    interface PropertyAdapter {
        fun read(): Float
        fun write(value: Float)
        fun settle(value: Float) {
            write(value)
        }
    }

    data class Lifecycle(
        val animationId: Long,
        val slotKey: String,
        val nodeId: Int,
        val property: String,
        val status: String,
        val reason: String? = null,
    )

    private val transitions = linkedMapOf<String, ActiveTransition>()
    private val targetHistory = linkedMapOf<String, TargetHistory>()
    private val adapters = mutableMapOf<String, PropertyAdapter>()
    private var frameScheduled = false

    fun registerAdapter(slotKey: String, adapter: PropertyAdapter) {
        adapters[slotKey] = adapter
    }

    /**
     * Establish the first declarative value without animating it.
     *
     * Declarative AnimatedValue applies its first target immediately. A later
     * target for the same stable slot uses the adapter's then-live value.
     */
    fun prime(slotKey: String, target: Float) {
        require(target.isFinite()) { "Animation target must be finite" }
        require(adapters.containsKey(slotKey)) {
            "No adapter registered for slot: $slotKey"
        }
        transitions.remove(slotKey)?.let {
            publish(it, status = "cancelled", reason = "reprimed")
        }
        cancelFrameIfIdle()
        targetHistory[slotKey] =
            TargetHistory(
                lastTargetNanos = nowNanos(),
                lastTarget = target,
            )
    }

    fun unregisterSlot(slotKey: String, reason: String = "removed") {
        cancel(slotKey, reason = reason)
        targetHistory.remove(slotKey)
        adapters.remove(slotKey)
    }

    fun unregisterNode(nodeId: Int, reason: String = "node_removed") {
        val prefix = "view:$nodeId:"
        val keys =
            (adapters.keys + transitions.keys + targetHistory.keys)
                .filterTo(mutableSetOf()) { it.startsWith(prefix) }
        keys.forEach { unregisterSlot(it, reason) }
    }

    fun dispose() {
        for (transition in transitions.values.toList()) {
            publish(transition, status = "cancelled", reason = "disposed")
        }
        transitions.clear()
        targetHistory.clear()
        adapters.clear()
        if (frameScheduled) {
            frameClock.cancelFrame()
            frameScheduled = false
        }
    }

    /**
     * Start or retarget one native timeline.
     *
     * Duration is per tween segment. Springs settle at each destination before
     * advancing. A missing from-value always reads the current presentation
     * value from the adapter, so a delayed Python result cannot cause a jump.
     */
    @Suppress("LongParameterList")
    fun setTarget(
        animationId: Long,
        slotKey: String,
        nodeId: Int,
        property: String,
        spec: String,
        targets: List<Float>,
        fromValue: Float?,
        durationMs: Long,
        easing: String,
        dampingRatio: Float,
        stiffness: Float,
        restValueThreshold: Float,
        restVelocityThreshold: Float,
        retargetPolicy: String,
    ) {
        require(animationId >= 0L) { "Animation id must be non-negative" }
        require(spec == "tween" || spec == "spring") {
            "Animation spec must be tween or spring"
        }
        require(targets.isNotEmpty() && targets.all(Float::isFinite)) {
            "Animation targets must be non-empty and finite"
        }
        require(fromValue == null || fromValue.isFinite()) {
            "Animation from-value must be finite"
        }
        require(durationMs >= 0L) { "Animation duration must be non-negative" }
        require(dampingRatio.isFinite() && dampingRatio > 0f)
        require(stiffness.isFinite() && stiffness > 0f)
        require(restValueThreshold.isFinite() && restValueThreshold >= 0f)
        require(restVelocityThreshold.isFinite() && restVelocityThreshold >= 0f)
        require(
            retargetPolicy in
                setOf("restart", "maintain_velocity", "snap_to_end", "ignore"),
        ) {
            "Unknown retarget policy"
        }

        val adapter =
            requireNotNull(adapters[slotKey]) {
                "No adapter registered for slot: $slotKey"
            }
        val now = nowNanos()
        val previous = transitions[slotKey]
        if (previous != null && retargetPolicy == "ignore") {
            if (animationId > 0L) {
                lifecycleSink(
                    Lifecycle(
                        animationId,
                        slotKey,
                        nodeId,
                        property,
                        status = "cancelled",
                        reason = "ignored",
                    ),
                )
            }
            return
        }

        var start = fromValue ?: adapter.read()
        var carriedVelocity = 0f
        if (previous != null) {
            if (retargetPolicy == "snap_to_end") {
                start = previous.targets.last()
                adapter.write(start)
            }
            if (retargetPolicy == "maintain_velocity") {
                carriedVelocity = previous.velocity
            }
            transitions.remove(slotKey)
            publish(previous, status = "cancelled", reason = "replaced")
        }

        val history = targetHistory[slotKey]
        val intervalNanos =
            history?.lastTargetNanos?.let {
                (now - it).coerceAtLeast(1L)
            }
        val intervalMillis =
            intervalNanos?.let {
                (it / NANOS_PER_MILLISECOND)
                    .coerceAtLeast(1L)
            }
        val targetVelocity =
            if (history != null && intervalNanos != null) {
                val observed =
                    (targets.first() - history.lastTarget).toDouble() /
                        (
                            intervalNanos
                                .coerceAtLeast(NANOS_PER_MILLISECOND)
                                .toDouble() / NANOS_PER_SECOND.toDouble()
                        )
                observed.toFloat().takeIf(Float::isFinite) ?: 0f
            } else {
                0f
            }
        val effectiveDuration =
            if (spec == "tween") {
                if (retargetPolicy == "maintain_velocity") {
                    // Keep two observed update intervals of overlap. This is
                    // responsive under fast input while ensuring the next
                    // retarget normally arrives before velocity is settled.
                    effectiveRetargetDuration(
                        durationMs,
                        intervalMillis?.times(2L),
                        frameClock.frameIntervalMillis * 2L,
                    )
                } else {
                    effectiveRetargetDuration(
                        durationMs,
                        intervalMillis,
                        frameClock.frameIntervalMillis,
                    )
                }
            } else {
                -1L
            }
        val durationNanos =
            if (effectiveDuration >= 0L) {
                millisToNanos(effectiveDuration)
            } else {
                -1L
            }
        val preserveTweenVelocity =
            spec == "tween" &&
                (previous != null || history != null) &&
                retargetPolicy == "maintain_velocity"
        val initialVelocity =
            when {
                spec == "spring" -> carriedVelocity
                preserveTweenVelocity -> carriedVelocity
                durationNanos > 0L ->
                    tweenVelocity(
                        start = start,
                        target = targets.first(),
                        durationNanos = durationNanos,
                        easing = easing,
                        rawFraction = 0f,
                    )
                else -> 0f
            }

        val transition =
            ActiveTransition(
                animationId = animationId,
                slotKey = slotKey,
                nodeId = nodeId,
                property = property,
                targets = targets.toList(),
                targetIndex = 0,
                start = start,
                target = targets.first(),
                segmentStartNanos = now,
                declaredDurationMs = durationMs,
                durationNanos = durationNanos,
                easing = easing,
                isSpring = spec == "spring",
                current = start,
                velocity = initialVelocity,
                tweenInitialVelocity =
                    if (preserveTweenVelocity) carriedVelocity else null,
                tweenTerminalVelocity =
                    if (preserveTweenVelocity) targetVelocity else null,
                lastFrameNanos = now,
                springDampingRatio = dampingRatio,
                springStiffness = stiffness,
                restValueThreshold = restValueThreshold,
                restVelocityThreshold = restVelocityThreshold,
            )
        targetHistory[slotKey] =
            TargetHistory(
                lastTargetNanos = now,
                lastTarget = targets.first(),
            )

        if (spec == "tween" && durationMs == 0L) {
            adapter.settle(targets.last())
            transition.current = targets.last()
            complete(transition)
            cancelFrameIfIdle()
            return
        }
        if (settleEmptySegments(transition, adapter, now)) {
            complete(transition)
            cancelFrameIfIdle()
            return
        }
        transitions[slotKey] = transition
        scheduleFrameIfNeeded()
    }

    fun cancel(
        slotKey: String,
        animationId: Long = 0L,
        reason: String = "cancelled",
    ): Boolean {
        val active = transitions[slotKey] ?: return false
        if (animationId > 0L && active.animationId != animationId) return false
        transitions.remove(slotKey)
        targetHistory.remove(slotKey)
        publish(active, status = "cancelled", reason = reason)
        cancelFrameIfIdle()
        return true
    }

    fun readSlot(slotKey: String): Float =
        adapters[slotKey]?.read()
            ?: throw NoSuchElementException("No adapter registered for slot: $slotKey")

    fun writeSlot(slotKey: String, value: Float) {
        require(value.isFinite()) { "Presentation value must be finite" }
        adapters[slotKey]?.write(value)
            ?: throw NoSuchElementException("No adapter registered for slot: $slotKey")
    }

    fun hasSlot(slotKey: String): Boolean = adapters.containsKey(slotKey)

    fun hasActiveTransition(slotKey: String): Boolean =
        transitions.containsKey(slotKey)

    private fun advance(now: Long) {
        if (transitions.isEmpty()) return
        val iterator = transitions.iterator()
        while (iterator.hasNext()) {
            val (_, transition) = iterator.next()
            val adapter = adapters[transition.slotKey]
            if (adapter == null) {
                iterator.remove()
                publish(transition, "cancelled", "adapter_removed")
                continue
            }
            try {
                val segmentFinished =
                    if (transition.isSpring) {
                        advanceSpring(transition, adapter, now)
                    } else {
                        advanceTween(transition, adapter, now)
                    }
                if (!segmentFinished) continue

                if (advanceSegment(transition, adapter, now)) {
                    continue
                }
                iterator.remove()
                complete(transition)
            } catch (_: Throwable) {
                iterator.remove()
                publish(transition, "cancelled", "adapter_error")
            }
        }
    }

    private fun advanceTween(
        transition: ActiveTransition,
        adapter: PropertyAdapter,
        now: Long,
    ): Boolean {
        val rawFraction =
            if (transition.durationNanos <= 0L) {
                1f
            } else {
                (
                    (now - transition.segmentStartNanos).coerceAtLeast(0L)
                        .toDouble() / transition.durationNanos.toDouble()
                ).toFloat().coerceIn(0f, 1f)
            }
        val initialVelocity = transition.tweenInitialVelocity
        val terminalVelocity = transition.tweenTerminalVelocity
        if (
            initialVelocity != null &&
            terminalVelocity != null &&
            transition.durationNanos > 0L
        ) {
            val sample =
                velocityPreservingTween(
                    start = transition.start,
                    target = transition.target,
                    initialVelocity = initialVelocity,
                    terminalVelocity = terminalVelocity,
                    durationNanos = transition.durationNanos,
                    rawFraction = rawFraction,
                )
            transition.current = sample.first
            transition.velocity = sample.second
        } else {
            val fraction = easingValue(transition.easing, rawFraction)
            transition.current =
                transition.start +
                    (transition.target - transition.start) * fraction
            transition.velocity =
                tweenVelocity(
                    start = transition.start,
                    target = transition.target,
                    durationNanos = transition.durationNanos,
                    easing = transition.easing,
                    rawFraction = rawFraction,
                )
        }
        adapter.write(transition.current)
        if (rawFraction < 1f) return false
        transition.current = transition.target
        transition.velocity = 0f
        adapter.settle(transition.target)
        return true
    }

    private fun advanceSpring(
        transition: ActiveTransition,
        adapter: PropertyAdapter,
        now: Long,
    ): Boolean {
        val elapsedSeconds =
            (
                (now - transition.lastFrameNanos).coerceAtLeast(0L) /
                    NANOS_PER_SECOND.toDouble()
            ).toFloat()
        val step =
            springStep(
                value = transition.current,
                target = transition.target,
                velocity = transition.velocity,
                elapsedSeconds = elapsedSeconds,
                dampingRatio = transition.springDampingRatio,
                stiffness = transition.springStiffness,
            )
        transition.current = step.first
        transition.velocity = step.second
        transition.lastFrameNanos = now
        adapter.write(transition.current)
        if (
            !springAtRest(
                transition.current,
                transition.target,
                transition.velocity,
                transition.restValueThreshold,
                transition.restVelocityThreshold,
            )
        ) {
            return false
        }
        transition.current = transition.target
        transition.velocity = 0f
        adapter.settle(transition.target)
        return true
    }

    /** Return true when another non-empty segment is ready. */
    private fun advanceSegment(
        transition: ActiveTransition,
        adapter: PropertyAdapter,
        now: Long,
    ): Boolean {
        transition.targetIndex += 1
        if (transition.targetIndex >= transition.targets.size) return false
        transition.start = transition.current
        transition.target = transition.targets[transition.targetIndex]
        transition.segmentStartNanos = now
        transition.lastFrameNanos = now
        transition.velocity = 0f
        transition.tweenInitialVelocity = null
        transition.tweenTerminalVelocity = null
        transition.durationNanos =
            if (transition.isSpring) {
                -1L
            } else {
                millisToNanos(transition.declaredDurationMs)
            }
        return !settleEmptySegments(transition, adapter, now)
    }

    /**
     * Skip destinations equal to the current value. Returns true if the full
     * timeline completed without requiring a frame.
     */
    private fun settleEmptySegments(
        transition: ActiveTransition,
        adapter: PropertyAdapter,
        now: Long,
    ): Boolean {
        while (transition.start == transition.target) {
            adapter.settle(transition.target)
            transition.current = transition.target
            transition.targetIndex += 1
            if (transition.targetIndex >= transition.targets.size) return true
            transition.start = transition.current
            transition.target = transition.targets[transition.targetIndex]
            transition.segmentStartNanos = now
            transition.lastFrameNanos = now
            transition.velocity = 0f
            transition.tweenInitialVelocity = null
            transition.tweenTerminalVelocity = null
            transition.durationNanos =
                if (transition.isSpring) {
                    -1L
                } else {
                    millisToNanos(transition.declaredDurationMs)
                }
        }
        return false
    }

    private fun complete(transition: ActiveTransition) {
        publish(transition, status = "completed", reason = null)
    }

    private fun publish(
        transition: ActiveTransition,
        status: String,
        reason: String?,
    ) {
        if (transition.animationId <= 0L) return
        lifecycleSink(
            Lifecycle(
                animationId = transition.animationId,
                slotKey = transition.slotKey,
                nodeId = transition.nodeId,
                property = transition.property,
                status = status,
                reason = reason,
            ),
        )
    }

    private fun scheduleFrameIfNeeded() {
        if (transitions.isEmpty() || frameScheduled) return
        frameScheduled = true
        frameClock.postFrame { frameTimeNanos ->
            frameScheduled = false
            advance(frameTimeNanos)
            scheduleFrameIfNeeded()
        }
    }

    private fun cancelFrameIfIdle() {
        if (transitions.isEmpty() && frameScheduled) {
            frameClock.cancelFrame()
            frameScheduled = false
        }
    }

    companion object {
        private const val NANOS_PER_MILLISECOND = 1_000_000L
        private const val NANOS_PER_SECOND = 1_000_000_000L
        private const val MAX_SPRING_FRAME_SECONDS = 0.064f
        private const val MAX_SPRING_STEP_SECONDS = 1f / 240f
        private const val MAX_MONOTONIC_TANGENT_RATIO = 3.0

        fun springStep(
            value: Float,
            target: Float,
            velocity: Float,
            elapsedSeconds: Float,
            dampingRatio: Float,
            stiffness: Float,
        ): Pair<Float, Float> {
            var nextValue = value
            var nextVelocity = velocity
            var remaining = elapsedSeconds.coerceIn(0f, MAX_SPRING_FRAME_SECONDS)
            val resolvedDampingRatio = dampingRatio.coerceAtLeast(0.01f)
            val resolvedStiffness = stiffness.coerceAtLeast(0.01f)
            val damping = 2f * resolvedDampingRatio * sqrt(resolvedStiffness)
            while (remaining > 0f) {
                val step = min(remaining, MAX_SPRING_STEP_SECONDS)
                val acceleration =
                    resolvedStiffness * (target - nextValue) -
                        damping * nextVelocity
                nextVelocity += acceleration * step
                nextValue += nextVelocity * step
                remaining -= step
            }
            return nextValue to nextVelocity
        }

        fun springAtRest(
            value: Float,
            target: Float,
            velocity: Float,
            valueThreshold: Float,
            velocityThreshold: Float,
        ): Boolean =
            abs(value - target) <= valueThreshold &&
                abs(velocity) <= velocityThreshold

        fun effectiveRetargetDuration(
            declaredDuration: Long,
            retargetInterval: Long?,
            frameDuration: Long,
        ): Long {
            val declared = declaredDuration.coerceAtLeast(0L)
            val interval = retargetInterval
            if (declared == 0L || interval == null || interval >= declared) {
                return declared
            }
            return max(frameDuration.coerceAtLeast(1L), interval)
                .coerceAtMost(declared)
        }

        internal fun easingValue(name: String, raw: Float): Float {
            val value = raw.coerceIn(0f, 1f)
            return when (name) {
                "linear" -> value
                "ease_in" -> value * value
                "ease_out" -> 1f - (1f - value) * (1f - value)
                "ease_in_out" ->
                    if (value < 0.5f) {
                        2f * value * value
                    } else {
                        1f - ((-2f * value + 2f) * (-2f * value + 2f)) / 2f
                    }
                "overshoot" -> {
                    val shifted = value - 1f
                    val c1 = 1.70158f
                    val c3 = c1 + 1f
                    1f + c3 * shifted * shifted * shifted +
                        c1 * shifted * shifted
                }
                "bounce" -> bounceOut(value)
                else -> error("Unknown easing: $name")
            }
        }

        /**
         * Sample a monotonic cubic Hermite tween between two moving targets.
         *
         * Requested endpoint velocities are limited against the segment slope.
         * This retains velocity when it is safe, but prevents a fast target
         * stream or an abrupt reversal from overshooting the target and feeding
         * an even larger velocity into the next retarget.
         */
        internal fun velocityPreservingTween(
            start: Float,
            target: Float,
            initialVelocity: Float,
            terminalVelocity: Float,
            durationNanos: Long,
            rawFraction: Float,
        ): Pair<Float, Float> {
            if (durationNanos <= 0L) return target to 0f
            val durationSeconds =
                durationNanos.toDouble() / NANOS_PER_SECOND.toDouble()
            val distance = target.toDouble() - start.toDouble()
            if (distance == 0.0) return target to 0f
            val segmentVelocity = distance / durationSeconds
            var initialRatio =
                if (initialVelocity.isFinite()) {
                    initialVelocity.toDouble() / segmentVelocity
                } else {
                    0.0
                }
            var terminalRatio =
                if (terminalVelocity.isFinite()) {
                    terminalVelocity.toDouble() / segmentVelocity
                } else {
                    0.0
                }

            // A tangent pointing away from this segment's target necessarily
            // overshoots. Drop it at a true direction reversal.
            initialRatio = initialRatio.coerceAtLeast(0.0)
            terminalRatio = terminalRatio.coerceAtLeast(0.0)

            // Fritsch-Carlson limiter for a single monotonic Hermite segment.
            val ratioLength =
                sqrt(
                    initialRatio * initialRatio +
                        terminalRatio * terminalRatio,
                )
            if (ratioLength > MAX_MONOTONIC_TANGENT_RATIO) {
                val scale = MAX_MONOTONIC_TANGENT_RATIO / ratioLength
                initialRatio *= scale
                terminalRatio *= scale
            }
            val initialTangent =
                initialRatio * segmentVelocity * durationSeconds
            val terminalTangent =
                terminalRatio * segmentVelocity * durationSeconds

            val fraction = rawFraction.coerceIn(0f, 1f).toDouble()
            val fraction2 = fraction * fraction
            val fraction3 = fraction2 * fraction

            val h00 = 2.0 * fraction3 - 3.0 * fraction2 + 1.0
            val h10 = fraction3 - 2.0 * fraction2 + fraction
            val h01 = -2.0 * fraction3 + 3.0 * fraction2
            val h11 = fraction3 - fraction2
            val value =
                h00 * start.toDouble() +
                    h10 * initialTangent +
                    h01 * target.toDouble() +
                    h11 * terminalTangent

            val dh00 = 6.0 * fraction2 - 6.0 * fraction
            val dh10 = 3.0 * fraction2 - 4.0 * fraction + 1.0
            val dh01 = -6.0 * fraction2 + 6.0 * fraction
            val dh11 = 3.0 * fraction2 - 2.0 * fraction
            val velocity =
                (
                    dh00 * start.toDouble() +
                        dh10 * initialTangent +
                        dh01 * target.toDouble() +
                        dh11 * terminalTangent
                ) / durationSeconds
            return value.toFloat() to velocity.toFloat()
        }

        private fun tweenVelocity(
            start: Float,
            target: Float,
            durationNanos: Long,
            easing: String,
            rawFraction: Float,
        ): Float {
            if (durationNanos <= 0L) return 0f
            val durationSeconds =
                durationNanos.toDouble() / NANOS_PER_SECOND.toDouble()
            return (
                (target - start).toDouble() *
                    easingDerivative(easing, rawFraction).toDouble() /
                    durationSeconds
            ).toFloat()
        }

        internal fun easingDerivative(name: String, raw: Float): Float {
            val value = raw.coerceIn(0f, 1f)
            return when (name) {
                "linear" -> 1f
                "ease_in" -> 2f * value
                "ease_out" -> 2f * (1f - value)
                "ease_in_out" ->
                    if (value < 0.5f) 4f * value else 4f * (1f - value)
                "overshoot" -> {
                    val shifted = value - 1f
                    val c1 = 1.70158f
                    val c3 = c1 + 1f
                    3f * c3 * shifted * shifted + 2f * c1 * shifted
                }
                "bounce" -> bounceOutDerivative(value)
                else -> error("Unknown easing: $name")
            }
        }

        private fun bounceOut(value: Float): Float {
            val n1 = 7.5625f
            val d1 = 2.75f
            return when {
                value < 1f / d1 -> n1 * value * value
                value < 2f / d1 -> {
                    val shifted = value - 1.5f / d1
                    n1 * shifted * shifted + 0.75f
                }
                value < 2.5f / d1 -> {
                    val shifted = value - 2.25f / d1
                    n1 * shifted * shifted + 0.9375f
                }
                else -> {
                    val shifted = value - 2.625f / d1
                    n1 * shifted * shifted + 0.984375f
                }
            }
        }

        private fun bounceOutDerivative(value: Float): Float {
            val n1 = 7.5625f
            val d1 = 2.75f
            return when {
                value < 1f / d1 -> 2f * n1 * value
                value < 2f / d1 -> 2f * n1 * (value - 1.5f / d1)
                value < 2.5f / d1 -> 2f * n1 * (value - 2.25f / d1)
                else -> 2f * n1 * (value - 2.625f / d1)
            }
        }

        private fun millisToNanos(durationMillis: Long): Long =
            durationMillis
                .coerceIn(0L, Long.MAX_VALUE / NANOS_PER_MILLISECOND) *
                NANOS_PER_MILLISECOND
    }

    private data class ActiveTransition(
        val animationId: Long,
        val slotKey: String,
        val nodeId: Int,
        val property: String,
        val targets: List<Float>,
        var targetIndex: Int,
        var start: Float,
        var target: Float,
        var segmentStartNanos: Long,
        val declaredDurationMs: Long,
        var durationNanos: Long,
        val easing: String,
        val isSpring: Boolean,
        var current: Float,
        var velocity: Float,
        var tweenInitialVelocity: Float?,
        var tweenTerminalVelocity: Float?,
        var lastFrameNanos: Long,
        val springDampingRatio: Float,
        val springStiffness: Float,
        val restValueThreshold: Float,
        val restVelocityThreshold: Float,
    )

    private data class TargetHistory(
        val lastTargetNanos: Long,
        val lastTarget: Float,
    )
}
