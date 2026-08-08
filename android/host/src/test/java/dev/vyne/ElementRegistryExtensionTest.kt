package dev.vyne

import dev.vyne.generated.ElementContracts
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * Extension registration contract tests (EXT-K1).
 *
 * The ElementRegistry is the single source of truth for extension kinds:
 * duplicate rejection, freeze semantics, prop validity (generic + widget-
 * specific), and the query surface Python uses at startup.
 */
class ElementRegistryExtensionTest {

    private fun timerRingSpec() = ElementSpec(
        kind = "TimerRing",
        create = { error("create must not be invoked in registry tests") },
        props = mapOf(
            "progress" to { _, _, _ -> },
            "ring_color" to { _, _, _ -> },
        ),
        events = mapOf(
            "complete" to { _, _ -> { } },
        ),
    )

    @Test
    fun registerAndLookup() {
        val registry = ElementRegistry()
        registry.register(timerRingSpec())
        assertTrue(registry.hasKind("TimerRing"))
        assertEquals("TimerRing", registry.get("TimerRing").kind)
        assertEquals(setOf("TimerRing"), registry.allKinds())
    }

    @Test
    fun duplicateKindRejected() {
        val registry = ElementRegistry()
        registry.register(timerRingSpec())
        assertFailsWith<IllegalStateException> {
            registry.register(timerRingSpec())
        }
        // Core kinds are already registered by the host: an extension
        // claiming a core kind must fail the same way.
        val core = ElementRegistry()
        core.register(
            ElementSpec(kind = "Text", create = { error("unused") }),
        )
        assertFailsWith<IllegalStateException> {
            core.register(timerRingSpec().copy(kind = "Text"))
        }
    }

    @Test
    fun freezeBlocksRegistration() {
        val registry = ElementRegistry()
        registry.register(timerRingSpec())
        registry.freeze()
        assertTrue(registry.isFrozen)
        assertFailsWith<IllegalStateException> {
            registry.register(ElementSpec(kind = "Late", create = { error("unused") }))
        }
    }

    @Test
    fun isValidPropCoreKindsUnchanged() {
        val registry = ElementRegistry()
        registry.register(timerRingSpec())
        assertTrue(registry.isValidProp("text", "Text"))
        assertTrue(registry.isValidProp("width", "Text"))
        assertFalse(registry.isValidProp("bogus", "Text"))
    }

    @Test
    fun isValidPropExtensionKind() {
        val registry = ElementRegistry()
        registry.register(timerRingSpec())
        // Generic props apply to extension kinds.
        assertTrue(registry.isValidProp("width", "TimerRing"))
        assertTrue(registry.isValidProp("background_color", "TimerRing"))
        assertTrue(registry.isValidProp("opacity", "TimerRing"))
        // Widget-specific props from the spec.
        assertTrue(registry.isValidProp("progress", "TimerRing"))
        assertTrue(registry.isValidProp("ring_color", "TimerRing"))
        // Unknown and core-widget props are rejected.
        assertFalse(registry.isValidProp("bogus", "TimerRing"))
        assertFalse(registry.isValidProp("text", "TimerRing"))
        // Unknown kind.
        assertFalse(registry.isValidProp("width", "NoSuchKind"))
    }

    @Test
    fun extensionKindsQueryExposesOnlyNonCoreKinds() {
        val registry = ElementRegistry()
        registry.register(timerRingSpec())
        registry.register(
            ElementSpec(
                kind = "Gauge",
                create = { error("unused") },
                props = mapOf("value" to { _, _, _ -> }),
            ),
        )
        val kinds = registry.extensionKinds()
        assertEquals(setOf("TimerRing", "Gauge"), kinds.keys)
        assertEquals(setOf("progress", "ring_color"), kinds.getValue("TimerRing").props)
        assertEquals(setOf("complete"), kinds.getValue("TimerRing").events)
        assertEquals(setOf("value"), kinds.getValue("Gauge").props)
        // Generic props are not listed — they apply to every kind.
        assertFalse("width" in kinds.getValue("TimerRing").props)
        // Core kinds never appear in the query.
        for (kind in ElementContracts.KINDS) {
            assertFalse(kind in kinds, "Core kind '$kind' leaked into extensionKinds()")
        }
    }

    @Test
    fun genericPropsAreTheIntersectionOfCoreKinds() {
        val expected = ElementContracts.ALL_PROPS_BY_KIND.values
            .reduce { a, b -> a intersect b }
        assertEquals(expected, ElementContracts.GENERIC_PROPS)
        assertNotNull(ElementContracts.GENERIC_PROPS)
        assertTrue("width" in ElementContracts.GENERIC_PROPS)
        assertFalse("text" in ElementContracts.GENERIC_PROPS)
    }
}
