package dev.vyne

/** An Android event record passed directly to Python through Chaquopy. */
data class NativeEvent(
    val sequence: Long,
    val target: Int,
    val name: String,
    val handler: Int,
    val payload: Map<String, Any?>,
    val delivery: String = "all",
)
