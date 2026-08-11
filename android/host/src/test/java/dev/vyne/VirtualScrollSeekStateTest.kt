package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class VirtualScrollSeekStateTest {
    @Test
    fun initialEmitThrottleLatestAndFinalBypass() {
        val state = VirtualScrollSeekState()
        state.beginGesture()

        assertEquals(VirtualScrollSeekEmission(100, false), state.updateTarget(100, 1_000, false))
        assertNull(state.updateTarget(200, 1_010, false))
        assertEquals(200, state.provisionalTarget)
        assertEquals(VirtualScrollSeekEmission(300, false), state.updateTarget(300, 1_032, false))
        assertEquals(VirtualScrollSeekEmission(350, true), state.updateTarget(350, 1_033, true))
    }

    @Test
    fun matchingRevealClearsOnlyMatchingProvisionalTarget() {
        val state = VirtualScrollSeekState()
        state.updateTarget(100, 0, false)
        state.updateTarget(200, 32, false)

        assertTrue(state.acceptReveal(100))
        assertEquals(200, state.provisionalTarget)
        // Any prepared older reveal is safe, but cannot clear the latest.
        assertTrue(state.acceptReveal(999))
        assertEquals(200, state.provisionalTarget)
        // Float dp↔px round trips may differ by one host pixel.
        assertTrue(state.acceptReveal(201))
        assertNull(state.provisionalTarget)
    }

    @Test
    fun finalWatchdogRetriesTwiceThenResets() {
        val state = VirtualScrollSeekState()
        state.updateTarget(500, 0, true)

        assertEquals(VirtualScrollSeekEmission(500, true), state.watchdog(0))
        assertEquals(VirtualScrollSeekEmission(500, true), state.watchdog(0))
        assertNull(state.watchdog(0))
        assertNull(state.provisionalTarget)
        assertFalse(state.finalPending)
    }

    @Test
    fun acceptedFinalRevealStopsRetry() {
        val state = VirtualScrollSeekState()
        state.updateTarget(500, 0, true)
        assertTrue(state.acceptReveal(500))
        assertNull(state.watchdog(0))
        assertFalse(state.finalPending)
    }

    @Test
    fun candidateListenerRemovalPreservesStateAndSuppressionCoversLayoutEcho() {
        val host = VirtualScrollSeekHostState(vertical = true)
        val emitted = mutableListOf<Int>()
        host.setListener { _, y, _, _ -> emitted.add(y) }
        host.beginGesture()
        host.update(300, 0, final = true)
        assertEquals(listOf(300), emitted)
        assertEquals(300, host.displayOffset(0))

        assertTrue(host.acceptReveal(0, 300, 100))
        assertTrue(host.consumeMetricsSuppression(0, 300, 101))
        // A following layout observation at the same target is also dropped.
        assertTrue(host.consumeMetricsSuppression(0, 300, 102))
        // Real movement clears suppression immediately.
        assertFalse(host.consumeMetricsSuppression(0, 299, 103))
        assertFalse(host.consumeMetricsSuppression(0, 300, 104))

        host.update(400, 200, final = false)
        host.setListener(null)
        assertEquals(400, host.displayOffset(0))
        assertFalse(host.enabled)
        host.setListener { _, _, _, _ -> }
        assertEquals(400, host.displayOffset(0))
        host.reset()
        assertEquals(0, host.displayOffset(0))
    }

    @Test
    fun horizontalHostMapsOnlyX() {
        val host = VirtualScrollSeekHostState(vertical = false)
        var payload: List<Any>? = null
        host.setListener { x, y, final, time -> payload = listOf(x, y, final, time) }
        host.beginGesture()
        host.update(250, 44, final = false)
        assertEquals(listOf(250, 0, false, 44L), payload)
    }
}
