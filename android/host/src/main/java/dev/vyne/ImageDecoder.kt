package dev.vyne

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.LruCache
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Mechanical decode tool for the Image widget.
 *
 * Python owns fetching; this tool only turns a data URI
 * (`data:image/png;base64,...`) into a bitmap and applies it off the UI
 * thread. Decoded bitmaps are cached in memory by source so re-renders and
 * list cells that reuse a source never re-decode.
 */
internal class ImageDecoder {
    private val memoryCache = object : LruCache<String, Bitmap>(MAX_MEMORY_BYTES) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount
    }
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()

    /**
     * Decode `dataUri` and apply it to `target` on the UI thread.
     * `isCurrent` is re-checked on the UI thread; a source that changed
     * mid-decode is dropped.
     */
    fun load(
        dataUri: String,
        target: android.widget.ImageView,
        isCurrent: () -> Boolean,
    ) {
        memoryCache.get(dataUri)?.let { cached ->
            target.post {
                if (isCurrent()) target.setImageBitmap(cached)
            }
            return
        }
        executor.execute {
            try {
                val bitmap = decode(dataUri)
                target.post {
                    if (!isCurrent()) return@post
                    memoryCache.put(dataUri, bitmap)
                    target.setImageBitmap(bitmap)
                }
            } catch (_: Throwable) {
                // Decode failures leave the previous drawable in place.
            }
        }
    }

    fun dispose() {
        executor.shutdownNow()
    }

    private fun decode(dataUri: String): Bitmap {
        val comma = dataUri.indexOf(',')
        if (!dataUri.startsWith("data:") || comma < 0) {
            throw IllegalArgumentException("Not a data URI")
        }
        val encoded = dataUri.substring(comma + 1)
        val bytes = Base64.decode(encoded, Base64.DEFAULT)
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            ?: throw IllegalArgumentException("Bitmap decode failed")
    }

    private companion object {
        const val MAX_MEMORY_BYTES = 32 * 1024 * 1024
    }
}
