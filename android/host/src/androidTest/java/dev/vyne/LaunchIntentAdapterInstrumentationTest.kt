package dev.vyne

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LaunchIntentAdapterInstrumentationTest {
    @Test
    fun intentIsProjectedToBridgeSafeLaunchData() {
        val nested =
            Bundle().apply {
                putBoolean("enabled", true)
                putIntArray("ids", intArrayOf(2, 4))
            }
        val intent =
            Intent("dev.vyne.OPEN", Uri.parse("vyne://conversation/42")).apply {
                putExtra("route", "conversation")
                putExtra("nested", nested)
                putExtra("unsupported", Intent("dev.vyne.NESTED_INTENT"))
            }

        val launch = LaunchIntentAdapter.fromIntent(intent, sequence = 9L)

        assertEquals("dev.vyne.OPEN", launch.action)
        assertEquals("vyne://conversation/42", launch.uri)
        assertEquals(9L, launch.sequence)
        assertEquals("conversation", launch.extras["route"])
        assertFalse(launch.extras.containsKey("unsupported"))

        @Suppress("UNCHECKED_CAST")
        val normalizedNested = launch.extras["nested"] as Map<String, Any?>
        assertEquals(true, normalizedNested["enabled"])
        assertEquals(listOf(2, 4), normalizedNested["ids"])
    }

    @Test
    fun emptyIntentStillProducesAValidLaunch() {
        val launch = LaunchIntentAdapter.fromIntent(Intent(), sequence = 1L)

        assertEquals(null, launch.action)
        assertEquals(null, launch.uri)
        assertTrue(launch.extras.isEmpty())
        assertEquals(1L, launch.sequence)
    }
}
