package dev.vyne

/**
 * Renderer-internal transaction model.
 *
 * This is not a transport protocol: it has no encoding, version, or wire
 * identity. The Chaquopy host constructs these operations directly.
 */
internal data class RenderTransaction(
    val revision: Long?,
    val operations: List<RenderOperation>,
) {
    val logicalOperationCount: Int =
        operations.sumOf { it.logicalOperationCount }
}

internal sealed interface RenderOperation {
    val logicalOperationCount: Int
        get() = 1

    data class Clear(val id: Int) : RenderOperation
    data class Create(val id: Int, val kind: String) : RenderOperation
    data class SetProps(
        val id: Int,
        val props: Map<String, Any?>,
    ) : RenderOperation
    data class SetProp(
        val id: Int,
        val name: String,
        val value: Any?,
    ) : RenderOperation
    data class RemoveProp(val id: Int, val name: String) : RenderOperation
    data class Listen(
        val id: Int,
        val event: String,
        val handler: Int,
        val delivery: String,
    ) : RenderOperation
    data class Unlisten(val id: Int, val event: String) : RenderOperation
    data class InsertChild(
        val parent: Int,
        val child: Int,
        val index: Int,
    ) : RenderOperation
    data class MoveChild(
        val parent: Int,
        val child: Int,
        val index: Int,
    ) : RenderOperation
    data class RemoveChild(val parent: Int, val child: Int) : RenderOperation
    data class Remove(val id: Int) : RenderOperation
    data class ScrollTo(
        val id: Int,
        val offsetX: Float,
        val offsetY: Float,
        val animated: Boolean,
    ) : RenderOperation
    data class MotionSetTarget(
        val animationId: Long,
        val slotKey: String,
        val nodeId: Int,
        val property: String,
        val targets: List<Float>,
        val slotId: String?,
        val specType: String,
        val fromValue: Float?,
        val durationMs: Long,
        val easing: String,
        val dampingRatio: Float,
        val stiffness: Float,
        val restValueThreshold: Float,
        val restVelocityThreshold: Float,
        val retargetPolicy: String,
    ) : RenderOperation
    data class MotionCancel(
        val animationId: Long,
        val slotKey: String,
    ) : RenderOperation
    data class MotionDriverSetTarget(
        val animationId: Long,
        val driverId: Long,
        val nodeId: Int,
        val property: String,
        val targets: List<Float>,
        val specType: String,
        val fromValue: Float?,
        val durationMs: Long,
        val easing: String,
        val dampingRatio: Float,
        val stiffness: Float,
        val restValueThreshold: Float,
        val restVelocityThreshold: Float,
        val retargetPolicy: String,
    ) : RenderOperation {
        val driverKey: String
            get() = "driver:$driverId"
    }
    data class MotionDriverCancel(
        val animationId: Long,
        val driverId: Long,
    ) : RenderOperation {
        val driverKey: String
            get() = "driver:$driverId"
    }
}
