/**
 * second_surface example — SMS-triggered WindowManager overlay.
 *
 * The trigger runs with the app closed: the system starts the process for
 * the receiver, Chaquopy's PyApplication boots Python, and the surface
 * runtime mounts with no Activity in existence. When the overlay
 * permission is missing, the extension degrades to a notification instead
 * of failing silently.
 */
package dev.vyne.ext.second_surface

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val first = messages.firstOrNull() ?: return
        val sender = first.displayOriginatingAddress ?: "unknown"
        val body = messages.joinToString("\n") { it.displayMessageBody ?: "" }
        SmsOverlayWindow.show(context, mapOf("sender" to sender, "body" to body))
    }
}
