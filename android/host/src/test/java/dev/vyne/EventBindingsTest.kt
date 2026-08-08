package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class EventBindingsTest {
    @Test
    fun removingNodesReturnsAndRemovesDetachCallbacks() {
        val bindings = EventBindings()
        var coreDetached = 0
        var extDetached = 0
        bindings.records[1 to "click"] = ListenerRecord(10, "latest")
        bindings.records[2 to "click"] =
            ListenerRecord(20, "all", detach = { coreDetached++ })
        bindings.records[2 to "complete"] =
            ListenerRecord(21, "all", detach = { extDetached++ })

        val detaches = bindings.removeNodes(setOf(1, 2))

        assertEquals(2, detaches.size)
        assertEquals(setOf<Pair<Int, String>>(), bindings.records.keys)
        // The caller decides WHEN to invoke; nothing invoked here.
        assertEquals(0, coreDetached)
        assertEquals(0, extDetached)
        detaches.forEach { it() }
        assertEquals(1, coreDetached)
        assertEquals(1, extDetached)
    }

    @Test
    fun clearReturnsEveryDetachExactlyOnce() {
        val bindings = EventBindings()
        var detaches = 0
        bindings.records[1 to "complete"] =
            ListenerRecord(10, "all", detach = { detaches++ })
        bindings.records[2 to "complete"] =
            ListenerRecord(20, "all", detach = { detaches++ })
        bindings.records[3 to "click"] = ListenerRecord(30, "all")  // core: no detach

        val returned = bindings.clear()

        assertEquals(2, returned.size)
        assertTrue(bindings.records.isEmpty())
        returned.forEach { it() }
        assertEquals(2, detaches)
        // A second clear finds nothing left to invoke.
        assertEquals(0, bindings.clear().size)
    }

    @Test
    fun eventSequencesRemainMonotonicAcrossListenerChanges() {
        val bindings = EventBindings()
        assertEquals(1L, bindings.nextEventSequence())
        bindings.clear()
        assertEquals(2L, bindings.nextEventSequence())
    }
}
