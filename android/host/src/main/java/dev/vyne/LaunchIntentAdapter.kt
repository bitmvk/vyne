package dev.vyne

import android.content.Intent
import android.os.Bundle

/** Immutable, bridge-safe projection of an Android Intent. */
internal data class NativeLaunchData(
    val action: String?,
    val uri: String?,
    val extras: Map<String, Any?>,
    val sequence: Long,
)

/**
 * Keeps Android framework objects out of Python.
 *
 * Only scalar, mapping, and sequence values cross the bridge. Unsupported
 * Parcelable or Serializable extras are omitted instead of making an otherwise
 * valid application launch fail.
 */
internal object LaunchIntentAdapter {
    private sealed interface Normalized {
        data class Value(val value: Any?) : Normalized
        object Unsupported : Normalized
    }

    fun fromIntent(intent: Intent, sequence: Long): NativeLaunchData {
        require(sequence >= 0L) { "Launch sequence must be non-negative" }
        val extras =
            try {
                normalizeBundle(intent.extras)
            } catch (_: Throwable) {
                emptyMap()
            }
        return NativeLaunchData(
            action = intent.action,
            uri = intent.dataString,
            extras = extras,
            sequence = sequence,
        )
    }

    @Suppress("DEPRECATION")
    private fun normalizeBundle(bundle: Bundle?): Map<String, Any?> {
        if (bundle == null || bundle.isEmpty) return emptyMap()
        val result = linkedMapOf<String, Any?>()
        for (key in bundle.keySet().sorted()) {
            val value =
                try {
                    bundle.get(key)
                } catch (_: Throwable) {
                    continue
                }
            val normalized = normalizeValue(value)
            if (normalized is Normalized.Value) {
                result[key] = normalized.value
            }
        }
        return result
    }

    private fun normalizeValue(value: Any?): Normalized =
        when (value) {
            null -> Normalized.Value(null)
            is Boolean,
            is Byte,
            is Short,
            is Int,
            is Long,
            is Float,
            is Double,
            -> Normalized.Value(value)
            is Char,
            is CharSequence,
            -> Normalized.Value(value.toString())
            is Bundle -> Normalized.Value(normalizeBundle(value))
            is BooleanArray -> Normalized.Value(value.toList())
            is ByteArray -> Normalized.Value(value.toList())
            is ShortArray -> Normalized.Value(value.toList())
            is IntArray -> Normalized.Value(value.toList())
            is LongArray -> Normalized.Value(value.toList())
            is FloatArray -> Normalized.Value(value.toList())
            is DoubleArray -> Normalized.Value(value.toList())
            is CharArray -> Normalized.Value(value.map(Char::toString))
            is Array<*> -> normalizeSequence(value.asList())
            is List<*> -> normalizeSequence(value)
            is Map<*, *> -> normalizeMap(value)
            else -> Normalized.Unsupported
        }

    private fun normalizeSequence(values: List<*>): Normalized {
        val result = ArrayList<Any?>(values.size)
        for (value in values) {
            when (val normalized = normalizeValue(value)) {
                is Normalized.Value -> result.add(normalized.value)
                Normalized.Unsupported -> return Normalized.Unsupported
            }
        }
        return Normalized.Value(result)
    }

    private fun normalizeMap(values: Map<*, *>): Normalized {
        if (values.keys.any { it !is String }) return Normalized.Unsupported
        val result = linkedMapOf<String, Any?>()
        for (key in values.keys.filterIsInstance<String>().sorted()) {
            when (val normalized = normalizeValue(values[key])) {
                is Normalized.Value -> result[key] = normalized.value
                Normalized.Unsupported -> return Normalized.Unsupported
            }
        }
        return Normalized.Value(result)
    }
}
