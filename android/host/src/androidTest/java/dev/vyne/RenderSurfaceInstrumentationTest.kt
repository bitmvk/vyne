/**
 * Device-backed coverage for the portable renderer surface (RenderSurface).
 *
 * These tests exercise the full architecture on-device: a second Python
 * runtime mounted by start_surface, committing through a second
 * DirectRenderHost into a second Renderer — no Activity involved.
 */
package dev.vyne

import android.os.SystemClock
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RenderSurfaceInstrumentationTest {

    private val context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    @org.junit.Before
    fun bootstrap() {
        // A receiver/service entry point may be the first component in the
        // process; make sure registration side effects ran before queries.
        AppBootstrap.ensureRegistered(context)
    }

    private fun surfaceRoot(name: String): RenderSurface? =
        RenderSurfaceRegistry.surface(name, context)

    private fun await(
        timeoutMs: Long = 20_000,
        condition: () -> Boolean,
    ) {
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        while (SystemClock.uptimeMillis() < deadline) {
            if (condition()) return
            Thread.sleep(50)
        }
        assertTrue("condition not met within ${timeoutMs}ms", condition())
    }

    private fun texts(root: android.view.View): List<String> {
        val found = mutableListOf<String>()
        fun walk(view: android.view.View) {
            if (view is TextView) found.add(view.text.toString())
            if (view is android.view.ViewGroup) {
                for (i in 0 until view.childCount) walk(view.getChildAt(i))
            }
        }
        walk(root)
        return found
    }

    @Test
    fun smsOverlaySurfaceIsDeclaredByTheExtension() {
        assertNotNull(
            "extension-declared surface should exist after bootstrap",
            RenderSurfaceRegistry.pythonModule("sms_overlay"),
        )
        assertNotNull(
            "extension-declared surface should exist after bootstrap",
            RenderSurfaceRegistry.pythonModule("lock_prompt"),
        )
    }

    @Test
    fun surfaceMountsItsOwnRuntimeAndRendersData() {
        val declared = surfaceRoot("sms_overlay")
        assertNotNull("sms_overlay surface must be declared", declared)
        val surface = declared!!

        try {
            surface.start(
                mapOf(
                    "show" to true,
                    "sender" to "555-0100",
                    "body" to "hello from the gate",
                )
            )
            await { surface.root.childCount > 0 }
            await {
                texts(surface.root).any { it.contains("555-0100") }
            }
            assertTrue(
                "overlay should render the SMS body",
                texts(surface.root).any { it.contains("hello from the gate") },
            )
        } finally {
            surface.dispose()
        }
    }

    @Test
    fun surfaceDeliverRerendersTheRoot() {
        val declared = surfaceRoot("sms_overlay")
        assertNotNull("sms_overlay surface must be declared", declared)
        val surface = declared!!

        try {
            surface.start(
                mapOf(
                    "show" to true,
                    "sender" to "first-sender",
                    "body" to "first body",
                )
            )
            await { texts(surface.root).any { it.contains("first-sender") } }

            surface.deliver(
                mapOf(
                    "show" to true,
                    "sender" to "second-sender",
                    "body" to "second body",
                )
            )
            await { texts(surface.root).any { it.contains("second-sender") } }
            assertTrue(
                "deliver should re-render with new data",
                texts(surface.root).any { it.contains("second body") },
            )
        } finally {
            surface.dispose()
        }
    }

    @Test
    fun surfaceStateChangesRerenderWithoutData() {
        val declared = surfaceRoot("sms_overlay")
        assertNotNull("sms_overlay surface must be declared", declared)
        val surface = declared!!

        try {
            surface.start(
                mapOf(
                    "show" to true,
                    "sender" to "tap-me",
                    "body" to "state test",
                )
            )
            await { texts(surface.root).any { it.contains("tap-me") } }

            // The Dismiss button flips a Python state cell; the tree then
            // re-renders with dismiss_requested=True. The extension's prop
            // handler fires OverlayDismissal — no action is registered in
            // this test, so the window teardown is a no-op, but the
            // re-render must still happen through the surface bridge.
            val dismiss = findButton(surface.root, "Dismiss")
            assertNotNull("Dismiss button should be rendered", dismiss)
            dismiss!!.performClick()
            await {
                texts(surface.root).any { it.contains("SMS received") } == false
            }
        } finally {
            surface.dispose()
        }
    }

    private fun findButton(
        root: android.view.View,
        label: String,
    ): android.view.View? {
        fun walk(view: android.view.View): android.view.View? {
            if (view is TextView && view.text.toString() == label) {
                // The click listener lives on the clickable button ancestor.
                var clickable: android.view.View? = view
                while (clickable != null && !clickable.isClickable) {
                    clickable = clickable.parent as? android.view.View
                }
                return clickable
            }
            if (view is android.view.ViewGroup) {
                for (i in 0 until view.childCount) {
                    walk(view.getChildAt(i))?.let { return it }
                }
            }
            return null
        }
        return walk(root)
    }
}
