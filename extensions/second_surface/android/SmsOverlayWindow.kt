/**
 * second_surface example — the WindowManager overlay attach point.
 *
 * Attaches the RenderSurface's root to a full-screen TYPE_APPLICATION_OVERLAY
 * window. The overlay survives the receiver (the surface runtime is owned by
 * the process-wide RenderSurfaceRegistry); the window is re-attached on each
 * show and removed when Python sets dismiss_requested.
 *
 * Extension-owned: window params, permission flow, and the graceful
 * notification fallback are all this extension's policy.
 */
package dev.vyne.ext.second_surface

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import dev.vyne.RenderSurface
import dev.vyne.RenderSurfaceRegistry

object SmsOverlayWindow {
    private const val TAG = "Vyne"
    private const val NOTIFICATION_CHANNEL = "sms_overlay"
    private const val NOTIFICATION_ID = 1

    @Volatile
    private var surface: RenderSurface? = null
    @Volatile
    private var attached = false

    /**
     * Show (or refresh) the overlay for one SMS. Safe from any thread; the
     * receiver runs on the main thread, so attach is synchronous.
     */
    fun show(context: Context, data: Map<String, Any?>) {
        val appContext = context.applicationContext
        if (!Settings.canDrawOverlays(appContext)) {
            notifyPermissionNeeded(appContext)
            return
        }
        val current = surface
            ?: RenderSurfaceRegistry.surface("sms_overlay", appContext)
                ?.also { surface = it }
            ?: run {
                Log.e(TAG, "sms_overlay surface is not declared")
                return
            }
        attach(appContext, current)
        current.start(mapOf("show" to true) + data)
    }

    /** Attach the surface root to a full-screen overlay window (idempotent). */
    private fun attach(context: Context, surface: RenderSurface) {
        if (attached) return
        val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val params =
            WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                    WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT,
            ).apply {
                gravity = Gravity.TOP or Gravity.START
            }
        wm.addView(surface.root, params)
        attached = true
        OverlayDismissal.register(surface.root) {
            detach(context)
        }
    }

    /** Remove the overlay window (idempotent). The surface stays warm. */
    fun detach(context: Context) {
        val current = surface ?: return
        if (!attached) return
        runCatching {
            val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
            wm.removeView(current.root)
        }
        OverlayDismissal.unregister(current.root)
        attached = false
    }

    private fun notifyPermissionNeeded(context: Context) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(
                    NOTIFICATION_CHANNEL,
                    "SMS overlay",
                    NotificationManager.IMPORTANCE_HIGH,
                )
            )
        }
        val openSettings =
            android.app.PendingIntent.getActivity(
                context,
                0,
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + context.packageName),
                ),
                android.app.PendingIntent.FLAG_UPDATE_CURRENT or
                    android.app.PendingIntent.FLAG_IMMUTABLE,
            )
        val notification =
            NotificationCompat.Builder(context, NOTIFICATION_CHANNEL)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("SMS overlay needs permission")
                .setContentText("Allow display over other apps to see SMS overlays.")
                .setContentIntent(openSettings)
                .setAutoCancel(true)
                .build()
        manager.notify(NOTIFICATION_ID, notification)
    }
}
