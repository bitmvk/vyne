package dev.vyne

import android.app.Instrumentation
import android.content.Intent
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.abs
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * True application-level acceptance tests.
 *
 * Unlike RendererInstrumentationTest, these launch MainActivity, execute the
 * packaged Python framework and test app, cross both bridge directions, apply
 * commits on Android Views, and inspect the resulting native hierarchy.
 */
@RunWith(AndroidJUnit4::class)
class FrameworkAcceptanceInstrumentationTest {
    private val instrumentation: Instrumentation
        get() = InstrumentationRegistry.getInstrumentation()

    private lateinit var activity: MainActivity
    private var imageServer: TinyHttpServer? = null

    @Before
    fun launchFrameworkApp() {
        startImageServer()
        val intent =
            Intent(
                instrumentation.targetContext,
                MainActivity::class.java,
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity = instrumentation.startActivitySync(intent) as MainActivity
        waitForView("acceptance-root", timeoutMs = 20_000)
    }

    @After
    fun closeFrameworkApp() {
        if (::activity.isInitialized && !activity.isFinishing) {
            instrumentation.runOnMainSync(activity::finish)
            instrumentation.waitForIdleSync()
        }
        imageServer?.stop()
        imageServer = null
    }

    /** Serve a tiny generated PNG for the app's urllib fetch (127.0.0.1). */
    private fun startImageServer() {
        val server = TinyHttpServer(9876, generatePng())
        server.start()
        imageServer = server
    }

    private fun generatePng(): ByteArray {
        val bitmap = android.graphics.Bitmap.createBitmap(
            64, 64, android.graphics.Bitmap.Config.ARGB_8888
        )
        android.graphics.Canvas(bitmap).drawColor(android.graphics.Color.RED)
        val out = java.io.ByteArrayOutputStream()
        bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, out)
        return out.toByteArray()
    }

    /** Minimal single-endpoint HTTP server for one GET request. */
    private class TinyHttpServer(
        private val port: Int,
        private val body: ByteArray,
    ) {
        private val serverSocket = java.net.ServerSocket().apply {
            reuseAddress = true
            // Force IPv4: some emulator images reject the default dual-stack
            // socket with EPERM.
            bind(
                java.net.InetSocketAddress(
                    java.net.Inet4Address.getByName("127.0.0.1"),
                    port,
                ),
            )
        }
        private val thread = Thread {
            while (!serverSocket.isClosed) {
                try {
                    val socket = serverSocket.accept()
                    Thread {
                        try {
                            socket.use { accepted ->
                                val reader = accepted.getInputStream().bufferedReader()
                                var line = reader.readLine()
                                while (line != null && line.isNotBlank()) line = reader.readLine()
                                val header =
                                    "HTTP/1.1 200 OK\r\n" +
                                        "Content-Length: ${body.size}\r\n" +
                                        "Content-Type: image/png\r\n" +
                                        "Connection: close\r\n\r\n"
                                accepted.getOutputStream().use { out ->
                                    out.write(header.toByteArray(Charsets.US_ASCII))
                                    out.write(body)
                                }
                            }
                        } catch (_: Throwable) {
                            // Client aborted; ignore.
                        }
                    }.start()
                } catch (_: Throwable) {
                    break
                }
            }
        }

        fun start() {
            thread.isDaemon = true
            thread.start()
        }

        fun stop() {
            runCatching { serverSocket.close() }
        }
    }

    @Test
    fun initialPythonTreeMountsThroughTheDirectBridge() {
        assertEquals("idle", text("phase-status"))
        assertEquals("0", text("count-status"))
        assertEquals("1:", text("launch-status"))
        assertNotNull(view("input-control"))
        assertNotNull(view("layout-box"))
    }

    @Test
    fun experimentalVirtualListsWindowJumpAndReorderEndToEnd() {
        // Vertical list: windowed, scrolls freely, jumps.
        waitForView("virtual-list-item-0")
        val scroll = view("public-virtual-list") as ScrollView
        val initialContent = scroll.getChildAt(0) as ViewGroup
        assertTrue(initialContent.childCount <= 12)
        assertTrue(findView("virtual-list-item-50") == null)

        val density = activity.resources.displayMetrics.density
        instrumentation.runOnMainSync {
            (scroll as RoundedScrollView).scrollToPosition(0, (300 * density).toInt())
        }
        waitForView("virtual-list-item-10", timeoutMs = 5_000)
        waitUntil(timeoutMs = 5_000) {
            findView("virtual-list-item-0") == null
        }

        click("virtual-list-jump")
        waitForView("virtual-list-item-50", timeoutMs = 5_000)
        waitUntil(timeoutMs = 5_000) {
            findView("virtual-list-item-10") == null
        }
        waitUntil(timeoutMs = 5_000) { scroll.scrollY > 0 }
        val content = scroll.getChildAt(0) as ViewGroup
        assertTrue(content.childCount <= 12)

        // Horizontal list: windows on the x axis and scrolls freely.
        waitForView("horizontal-item-0")
        val horizontal = view("public-horizontal-list") as RoundedHorizontalScrollView
        assertTrue(findView("horizontal-item-100") == null)
        instrumentation.runOnMainSync {
            horizontal.scrollToPosition((1_260 * density).toInt(), 0)
        }
        waitForView("horizontal-item-10", timeoutMs = 5_000)
        waitUntil(timeoutMs = 5_000) {
            findView("horizontal-item-0") == null
        }
        assertTrue((horizontal.getChildAt(0) as ViewGroup).childCount <= 12)

        // Dynamic keyed list: reorder and resize preserve window identity.
        waitForView("dynamic-item-0")
        assertTrue(findView("dynamic-item-99") == null)

        click("dynamic-reverse")
        waitForView("dynamic-item-99", timeoutMs = 5_000)
        waitUntil(timeoutMs = 5_000) { findView("dynamic-item-0") == null }

        click("dynamic-resize")
        waitForView("dynamic-item-19", timeoutMs = 5_000)
        waitUntil(timeoutMs = 5_000) { findView("dynamic-item-99") == null }
        assertTrue((view("public-dynamic-list") as ViewGroup)
            .getChildAt(0).let { it as ViewGroup }.childCount <= 12)
    }

    @Test
    fun urllibFetchIntoDataUriDisplaysInImageWidget() {
        val image = waitForView("network-image") as android.widget.ImageView
        assertEquals(null, image.drawable)

        click("load-image")
        waitForText("image-status", "loaded", timeoutMs = 15_000)
        waitUntil(timeoutMs = 15_000) {
            val current = view("network-image") as android.widget.ImageView
            current.drawable != null
        }
    }

    @Test
    fun synchronousCallbackUpdatesNativeText() {
        click("increment-button")
        waitForText("count-status", "1")
    }

    @Test
    fun asyncCallbackCommitsBeforeAndAfterAwait() {
        click("slow-button")
        waitForText("phase-status", "waiting")
        waitForText("phase-status", "done", timeoutMs = 3_000)
    }

    @Test
    fun waitingAsyncCallbackDoesNotBlockAnotherEvent() {
        click("slow-button")
        waitForText("phase-status", "waiting")
        click("increment-button")
        waitForText("count-status", "1")
        assertEquals("waiting", text("phase-status"))
        waitForText("phase-status", "done", timeoutMs = 3_000)
    }

    @Test
    fun manyAwaitingCallbacksAllResumeWithoutLostCommits() {
        repeat(16) { click("await-increment-button") }
        waitForText("count-status", "16", timeoutMs = 5_000)
    }

    @Test
    fun stateWritesInOneContinuationAppearTogether() {
        click("pair-button")
        waitForText("pair-status", "1:1")
    }

    @Test
    fun asyncFailureRollsBackItsCurrentContinuationAndRuntimeSurvives() {
        click("fail-button")
        waitForText("error-status", "1")
        SystemClock.sleep(250)
        assertEquals("1", text("error-status"))

        click("increment-button")
        waitForText("count-status", "1")
    }

    @Test
    fun AndroidToPythonAsyncCallbackCompletesEndToEnd() {
        Python.getInstance()
            .getModule("vyne_emulator_app")
            .callAttr("emit_external", "from-android")
        waitForText("external-status", "from-android", timeoutMs = 3_000)
    }

    @Test
    fun latestAndroidCallbackConvergesToNewestValue() {
        Python.getInstance()
            .getModule("vyne_emulator_app")
            .callAttr("emit_latest_many", 80)
        waitForText("latest-status", "79", timeoutMs = 5_000)
    }

    @Test
    fun warmIntentRerendersRootWhilePreservingState() {
        click("increment-button")
        waitForText("count-status", "1")

        val warmIntent =
            Intent(
                instrumentation.targetContext,
                MainActivity::class.java,
            ).apply {
                action = "dev.vyne.TEST_WARM"
                putExtra("marker", "accepted")
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP
                )
            }
        instrumentation.targetContext.startActivity(warmIntent)

        waitForText("launch-status", "2:dev.vyne.TEST_WARM")
        assertEquals("1", text("count-status"))
    }

    @Test
    fun nativeTextInputEventRoundTripsThroughPythonState() {
        val input = view("input-control") as EditText
        instrumentation.runOnMainSync {
            input.setText("round trip")
        }
        waitForText("input-status", "round trip")
        assertEquals("round trip", text("input-control"))
    }

    @Test
    fun keyedReorderMovesExistingNativeViews() {
        val firstA = view("order-item-a")
        val firstB = view("order-item-b")
        assertEquals(
            listOf("order-item-a", "order-item-b"),
            childDescriptions("order-container"),
        )

        click("reverse-button")
        waitUntil {
            childDescriptions("order-container") ==
                listOf("order-item-b", "order-item-a")
        }

        assertSame(firstA, view("order-item-a"))
        assertSame(firstB, view("order-item-b"))
    }

    @Test
    fun layoutDimensionsAndPresentationPropsReachNativeView() {
        val density = activity.resources.displayMetrics.density
        waitUntil { view("layout-box").width > 0 }
        val box = view("layout-box")

        assertTrue(abs(box.width - 100f * density) <= 1.5f)
        assertTrue(abs(box.height - 40f * density) <= 1.5f)
        assertTrue(abs(box.alpha - 0.75f) < 0.001f)
        assertTrue(abs(box.translationX - 3f * density) <= 1.5f)
        assertTrue(box.paddingLeft > 0)
    }

    @Test
    fun PythonAnimationRunsOnNativeFramesAndCompletionCommitsBack() {
        val target = view("animation-target")
        assertEquals(1f, target.alpha, 0.001f)

        click("animation-target")
        waitForText("animation-status", "completed", timeoutMs = 5_000)

        assertEquals(0.25f, target.alpha, 0.02f)
    }

    @Test
    fun backHandlerConsumesSystemBackPressWhenGuardEnabled() {
        click("back-guard-toggle")
        waitForText("back-guard-toggle", "disable back guard")

        pressBack()

        waitForText("back-status", "back consumed: 1", timeoutMs = 5_000)
        assertFalse(activity.isFinishing)
    }

    private fun pressBack() {
        instrumentation.runOnMainSync {
            activity.onBackPressedDispatcher.onBackPressed()
        }
    }

    @Test
    fun destroyingActivityCancelsOutstandingAsyncWorkCleanly() {
        click("slow-button")
        waitForText("phase-status", "waiting")
        instrumentation.runOnMainSync(activity::finish)
        waitUntil(timeoutMs = 5_000) {
            activity.isFinishing || activity.isDestroyed
        }
    }

    private fun click(description: String) {
        val target = view(description)
        instrumentation.runOnMainSync {
            assertTrue(
                "performClick failed for $description",
                target.performClick(),
            )
        }
        instrumentation.waitForIdleSync()
    }

    private fun text(description: String): String {
        val result = AtomicReference<String>()
        instrumentation.runOnMainSync {
            result.set((findView(description) as TextView).text.toString())
        }
        return result.get()
    }

    private fun childDescriptions(description: String): List<String> {
        val result = AtomicReference<List<String>>()
        instrumentation.runOnMainSync {
            val group = findView(description) as ViewGroup
            result.set(
                List(group.childCount) { index ->
                    group.getChildAt(index).contentDescription?.toString().orEmpty()
                }
            )
        }
        return result.get()
    }

    private fun view(description: String): View {
        val result = AtomicReference<View?>()
        instrumentation.runOnMainSync {
            result.set(findView(description))
        }
        return requireNotNull(result.get()) {
            "No native view with content description $description"
        }
    }

    private fun findView(description: String): View? =
        findView(activity.window.decorView, description)

    private fun findView(root: View, description: String): View? {
        if (root.contentDescription?.toString() == description) return root
        if (root !is ViewGroup) return null
        for (index in 0 until root.childCount) {
            val match = findView(root.getChildAt(index), description)
            if (match != null) return match
        }
        return null
    }

    private fun waitForView(
        description: String,
        timeoutMs: Long = 2_000,
    ): View {
        waitUntil(timeoutMs) {
            val found = AtomicReference<View?>()
            instrumentation.runOnMainSync {
                found.set(findView(description))
            }
            found.get() != null
        }
        return view(description)
    }

    private fun waitForText(
        description: String,
        expected: String,
        timeoutMs: Long = 2_000,
    ) {
        waitUntil(timeoutMs) {
            runCatching { text(description) }.getOrNull() == expected
        }
    }

    private fun waitUntil(
        timeoutMs: Long = 2_000,
        condition: () -> Boolean,
    ) {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (condition()) return
            SystemClock.sleep(20)
        }
        assertTrue("Condition not met within ${timeoutMs}ms", condition())
    }
}
