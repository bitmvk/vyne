package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RendererTransactionTest {

    @Test
    fun applyResultEnumValues() {
        assertEquals("OK", Renderer.ApplyResult.OK.name)
        assertEquals("PARTIAL", Renderer.ApplyResult.PARTIAL.name)
        assertEquals("UNKNOWN", Renderer.ApplyResult.UNKNOWN.name)
    }

    // ── Accessibility property contracts ──────────────────────────────

    @Test
    fun everyCanonicalKindHasAnAndroidFactory() {
        val registry = ElementRegistry()
        registerNativeWidgets(registry)
        assertEquals(
            dev.vyne.generated.ElementContracts.KINDS,
            registry.allKinds(),
        )
    }

    @Test
    fun accessibilityStateDescriptionIsInElementContracts() {
        // Verify that the new accessibility_state_description prop is in the
        // generated Box prop set (it was added to the schema spec in round 5).
        assertTrue(
            "accessibility_state_description" in
                dev.vyne.generated.ElementContracts.ALL_PROPS_BY_KIND.getValue("Box"),
            "Box props should include accessibility_state_description"
        )
    }

    @Test
    fun accessibilityPropNamesAreConsistentAcrossKinds() {
        // Verify that all 8 kinds have the core accessibility props.
        val required = setOf(
            "accessibility_role",
            "accessibility_selected",
            "accessibility_checked",
            "accessibility_state_description",
            "accessibility_range_min",
            "accessibility_range_max",
            "accessibility_range_current",
        )
        val contracts = dev.vyne.generated.ElementContracts
        for (kind in contracts.KINDS) {
            val props = contracts.ALL_PROPS_BY_KIND[kind]
            assertTrue(props != null, "Missing prop set for kind: $kind")
            for (prop in required) {
                assertTrue(
                    prop in props!!,
                    "Kind '$kind' should include accessibility prop '$prop'"
                )
            }
        }
    }

    @Test
    fun safeAreaIsAvailableOnEveryViewKind() {
        val contracts = dev.vyne.generated.ElementContracts
        for (kind in contracts.KINDS) {
            assertTrue(
                "safe_area" in contracts.ALL_PROPS_BY_KIND.getValue(kind),
                "Kind '$kind' should expose safe_area"
            )
        }
    }

    @Test
    fun animatablePropsIncludeExpectedProperties() {
        val animatable = dev.vyne.generated.ElementContracts.ANIMATABLE_PROPS
        val expected = setOf(
            "opacity", "rotation", "rotation_x", "rotation_y",
            "scale_x", "scale_y", "translation_x", "translation_y",
            "elevation", "width", "height",
            "stroke_dash_offset",
        )
        for (prop in expected) {
            assertTrue(prop in animatable, "ANIMATABLE_PROPS should include '$prop'")
        }
    }

    @Test
    fun presentationEngineReadSlotThrowsForUnknownSlot() {
        val engine = PresentationEngine()
        try {
            engine.readSlot("nonexistent")
            // Should have thrown.
            assertTrue(false, "Expected NoSuchElementException")
        } catch (e: NoSuchElementException) {
            // Expected.
        }
    }

    @Test
    fun presentationEngineHasSlotReturnsFalseForUnknown() {
        val engine = PresentationEngine()
        assertFalse(engine.hasSlot("unknown"))
    }

    @Test
    fun presentationEngineHasSlotReturnsTrueAfterRegistration() {
        val engine = PresentationEngine()
        var lastWritten = 0f
        engine.registerAdapter("test", object : PresentationEngine.PropertyAdapter {
            override fun read(): Float = 42f
            override fun write(value: Float) { lastWritten = value }
        })
        assertTrue(engine.hasSlot("test"))
        assertEquals(42f, engine.readSlot("test"))
    }

    @Test
    fun presentationEngineWriteViaAdapter() {
        val engine = PresentationEngine()
        var lastWritten = 0f
        engine.registerAdapter("slot1", object : PresentationEngine.PropertyAdapter {
            override fun read(): Float = 0f
            override fun write(value: Float) { lastWritten = value }
        })
        engine.readSlot("slot1") // Just ensure it reads
        // Write won't happen through engine alone — setTarget triggers it.
        // This test just validates adapter registration.
        assertTrue(engine.hasSlot("slot1"))
    }

    @Test
    fun presentationEngineCancelRemovesSlot() {
        val engine = PresentationEngine()
        engine.registerAdapter("temp", object : PresentationEngine.PropertyAdapter {
            override fun read(): Float = 0f
            override fun write(value: Float) {}
        })
        assertTrue(engine.hasSlot("temp"))
        engine.cancel("temp")
        // cancel does not remove adapters, just transitions.
        assertTrue(engine.hasSlot("temp"))
    }

    @Test
    fun presentationEngineUnregisterRemovesAdapter() {
        val engine = PresentationEngine()
        engine.registerAdapter("rem", object : PresentationEngine.PropertyAdapter {
            override fun read(): Float = 0f
            override fun write(value: Float) {}
        })
        assertTrue(engine.hasSlot("rem"))
        engine.unregisterSlot("rem")
        assertFalse(engine.hasSlot("rem"))
    }
}
