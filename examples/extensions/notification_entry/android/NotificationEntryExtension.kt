/**
 * Notification-entry example — native side.
 *
 * Demonstrates the extension-owned notification PendingIntent pattern:
 * - stable identity via requestCode (extras do NOT participate in
 *   PendingIntent identity — two notifications with the same requestCode
 *   silently share one PendingIntent),
 * - CLEAR_TOP | SINGLE_TOP flags so a warm tap lands on onNewIntent,
 * - FLAG_IMMUTABLE for the PendingIntent,
 * - plain action/extras (the host's LaunchIntentAdapter normalizes them).
 *
 * The framework provides NO notification API — the entry mechanism
 * (singleTop manifest, onNewIntent, RuntimeOwner cold/warm classification,
 * pre_launch) is host-owned; the notification itself is extension-owned.
 */
package dev.vyne.ext.notification

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import dev.vyne.ElementRegistry
import dev.vyne.MainActivity

object NotificationEntryExtension {

    /**
     * Registration entry point (generated registrant). This extension
     * registers no kinds — it demonstrates the notification entry pattern.
     */
    internal fun register(context: Context, registry: ElementRegistry) {
        // No kinds: the notification PendingIntent helper is the payload.
    }

    /**
     * Build the entry PendingIntent for one notification.
     *
     * @param entryKey stable per-notification identity: the same key updates
     *   the existing PendingIntent in place (FLAG_UPDATE_CURRENT); different
     *   keys always produce distinct PendingIntents.
     */
    fun notificationPendingIntent(
        context: Context,
        entryKey: String,
        action: String,
        extras: Map<String, Any?> = emptyMap(),
    ): PendingIntent =
        PendingIntent.getActivity(
            context,
            entryKey.hashCode(),
            entryIntent(context, entryKey, action, extras),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    /**
     * The entry Intent: targets MainActivity, carries plain action/extras,
     * and uses CLEAR_TOP|SINGLE_TOP so a warm tap lands on onNewIntent.
     * (Exposed separately because PendingIntent no longer exposes its
     * wrapped intent on current API levels.)
     */
    fun entryIntent(
        context: Context,
        entryKey: String,
        action: String,
        extras: Map<String, Any?> = emptyMap(),
    ): Intent =
        Intent(context, MainActivity::class.java).apply {
            this.action = action
            // Identity: the entryKey lives in the data URI. Intent data is
            // part of PendingIntent identity, so two distinct keys can never
            // merge — even when their request codes (String.hashCode)
            // collide. The host's LaunchIntentAdapter exposes it as
            // LaunchData.uri; the developer's own uri stays in extras.
            data = android.net.Uri.parse("vyne://entry/" + android.net.Uri.encode(entryKey))
            extras.forEach { (key, value) -> putExtraTyped(this, key, value) }
            flags =
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                    Intent.FLAG_ACTIVITY_SINGLE_TOP
        }

    /** Typed extras for the bridge-safe scalar domain (LaunchIntentAdapter). */
    private fun putExtraTyped(intent: Intent, key: String, value: Any?) {
        when (value) {
            null -> Unit
            is Boolean -> intent.putExtra(key, value)
            is Int -> intent.putExtra(key, value)
            is Long -> intent.putExtra(key, value)
            is Float -> intent.putExtra(key, value)
            is Double -> intent.putExtra(key, value)
            is String -> intent.putExtra(key, value)
            is CharSequence -> intent.putExtra(key, value.toString())
            else -> Unit // unsupported values are omitted (host normalization)
        }
    }
}
