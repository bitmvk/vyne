package dev.vyne

import android.app.PendingIntent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.vyne.ext.notification.NotificationEntryExtension
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.runner.RunWith

/**
 * Notification-entry example tests (EXT-K2): the extension-owned
 * PendingIntent pattern — stable requestCode identity, entry flags, plain
 * action/extras, immutability.
 */
@RunWith(AndroidJUnit4::class)
class NotificationEntryInstrumentationTest {

    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun sameEntryKeyYieldsSamePendingIntent() {
        val a = NotificationEntryExtension.notificationPendingIntent(
            context, "order_1", "notify.order", mapOf("id" to 7),
        )
        val b = NotificationEntryExtension.notificationPendingIntent(
            context, "order_1", "notify.order", mapOf("id" to 9),
        )
        // Same key + FLAG_UPDATE_CURRENT: the later call updates the same
        // PendingIntent (the new extras win), never a second identity.
        // PendingIntent.equals compares the wrapped intent's action/data/
        // type/class/categories AND the request code (extras excluded).
        assertTrue(a == b, "same entryKey must share one PendingIntent")
    }

    @Test
    fun differentEntryKeysYieldDistinctPendingIntents() {
        val a = NotificationEntryExtension.notificationPendingIntent(
            context, "order_1", "notify.order", mapOf("id" to 7),
        )
        val b = NotificationEntryExtension.notificationPendingIntent(
            context, "order_2", "notify.order", mapOf("id" to 8),
        )
        // Extras do NOT participate in PendingIntent identity: only the
        // requestCode (derived from entryKey) separates them.
        assertFalse(a == b, "different entryKeys must not collide")
    }

    @Test
    fun entryIntentCarriesPlainActionAndExtras() {
        val intent = NotificationEntryExtension.entryIntent(
            context, "order_1", "notify.order", mapOf("order_id" to 42, "route" to "shipped"),
        )
        assertEquals("notify.order", intent.action)
        assertEquals(42, intent.getIntExtra("order_id", -1))
        assertEquals("shipped", intent.getStringExtra("route"))
        assertTrue(intent.hasExtra("order_id"))
    }

    @Test
    fun entryIntentUsesEntryFlags() {
        val intent = NotificationEntryExtension.entryIntent(
            context, "order_1", "notify.order", emptyMap(),
        )
        val flags = intent.flags
        assertTrue(flags and android.content.Intent.FLAG_ACTIVITY_CLEAR_TOP != 0)
        assertTrue(flags and android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP != 0)
    }

    @Test
    fun entryIntentTargetsMainActivity() {
        val intent = NotificationEntryExtension.entryIntent(
            context, "order_1", "notify.order", emptyMap(),
        )
        assertEquals(MainActivity::class.java.name, intent.component!!.className)
    }

    @Test
    fun collidingRequestCodesStillYieldDistinctPendingIntents() {
        // "Aa" and "BB" share String.hashCode() (2112). The data-URI
        // identity (entryKey) must keep the PendingIntents distinct.
        val a = NotificationEntryExtension.notificationPendingIntent(
            context, "Aa", "notify.order", emptyMap(),
        )
        val b = NotificationEntryExtension.notificationPendingIntent(
            context, "BB", "notify.order", emptyMap(),
        )
        assertEquals("Aa".hashCode(), "BB".hashCode())
        assertFalse(a == b, "distinct keys must never merge, even on hashCode collision")
        // Same key still shares one identity.
        val a2 = NotificationEntryExtension.notificationPendingIntent(
            context, "Aa", "notify.order", emptyMap(),
        )
        assertTrue(a == a2)
    }
}
