/**
 * second_surface example — lock-screen prompt attach point.
 *
 * A dedicated showWhenLocked Activity: fullscreen UI over the keyguard,
 * wakes the screen, never unlocks the phone, never opens the main app.
 * The surface root is the Activity's content view — the same portable
 * Renderer machinery as the WindowManager overlay, different window kind.
 *
 * Triggered in the demo via `adb shell am start -n
 * dev.vyne/dev.vyne.ext.second_surface.PromptActivity` (a real product
 * would use a full-screen-intent notification from FCM).
 */
package dev.vyne.ext.second_surface

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import dev.vyne.RenderSurfaceRegistry

class PromptActivity : ComponentActivity() {
    private val surface by lazy {
        RenderSurfaceRegistry.surface("lock_prompt", this)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val current = surface
        if (current == null) {
            Log.e(TAG, "lock_prompt surface is not declared")
            finish()
            return
        }
        setContentView(current.root)
        OverlayDismissal.register(current.root) {
            runOnUiThread { if (!isFinishing) finish() }
        }
        val extras = intent.extras
        val data =
            buildMap {
                put("show", true)
                if (extras != null) {
                    extras.keySet().forEach { key ->
                        extras.get(key)?.let { put(key, it) }
                    }
                }
            }
        current.start(data)
    }

    override fun onDestroy() {
        surface?.let { OverlayDismissal.unregister(it.root) }
        super.onDestroy()
    }

    private companion object {
        const val TAG = "Vyne"
    }
}
