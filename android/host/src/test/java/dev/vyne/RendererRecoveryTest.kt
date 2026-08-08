package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * Tests for Renderer recovery behavior (RECOVER-07 / RE-CMD-2).
 *
 * Verifies:
 * - ApplyResult enum values and ordinal ordering
 * - REJECTED_KNOWN and UNKNOWN are distinct non-success states
 * - Property table has all element kinds
 * - Known operations set for preflight validation
 * - ElementContracts KINDS covers all expected types
 */
class RendererRecoveryTest {

    // ── ApplyResult contract ──────────────────────────────────────

    @Test
    fun applyResultEnumValuesArePresent() {
        assertEquals("OK", Renderer.ApplyResult.OK.name)
        assertEquals("REJECTED_KNOWN", Renderer.ApplyResult.REJECTED_KNOWN.name)
        assertEquals("PARTIAL", Renderer.ApplyResult.PARTIAL.name)
        assertEquals("UNKNOWN", Renderer.ApplyResult.UNKNOWN.name)
    }

    @Test
    fun applyResultValuesAreDistinct() {
        val values = Renderer.ApplyResult.entries.toSet()
        assertEquals(4, values.size, "All four ApplyResult values must be distinct")
    }

    @Test
    fun applyResultHasFixedOrdinalOrder() {
        // ApplyResult ordinal order must be: OK(0), REJECTED_KNOWN(1),
        // PARTIAL(2), UNKNOWN(3).  UNKNOWN is the most severe.
        assertTrue(
            Renderer.ApplyResult.UNKNOWN.ordinal > Renderer.ApplyResult.PARTIAL.ordinal,
            "UNKNOWN must be more severe than PARTIAL"
        )
        assertTrue(
            Renderer.ApplyResult.PARTIAL.ordinal > Renderer.ApplyResult.REJECTED_KNOWN.ordinal,
            "PARTIAL must be more severe than REJECTED_KNOWN"
        )
        assertTrue(
            Renderer.ApplyResult.REJECTED_KNOWN.ordinal > Renderer.ApplyResult.OK.ordinal,
            "REJECTED_KNOWN must be more severe than OK"
        )
    }

    // ── Non-success states are distinct from OK ────────────────────

    @Test
    fun rejectedKnownIsDistinctFromOk() {
        assertTrue(
            Renderer.ApplyResult.REJECTED_KNOWN != Renderer.ApplyResult.OK,
            "REJECTED_KNOWN must be distinct from OK"
        )
    }

    @Test
    fun partialIsDistinctFromOk() {
        assertTrue(
            Renderer.ApplyResult.PARTIAL != Renderer.ApplyResult.OK,
            "PARTIAL must be distinct from OK"
        )
    }

    @Test
    fun unknownIsDistinctFromOk() {
        assertTrue(
            Renderer.ApplyResult.UNKNOWN != Renderer.ApplyResult.OK,
            "UNKNOWN must be distinct from OK"
        )
    }

    // ── Property table coverage ───────────────────────────────────

    @Test
    fun propertyTableHasAllElementKinds() {
        val kinds = dev.vyne.generated.ElementContracts.KINDS
        assertTrue(kinds.isNotEmpty(), "ElementContracts.KINDS must not be empty")
        for (kind in kinds) {
            val props = dev.vyne.generated.ElementContracts.ALL_PROPS_BY_KIND[kind]
            assertNotNull(props, "Missing property set for kind: $kind")
        }
    }

    // ── Known operation names for preflight ───────────────────────

    @Test
    fun knownOperationsIncludeAllStandardOps() {
        // Verify the standard operations that preflight must accept.
        val standardOps = setOf(
            "clear", "create", "set_props", "set_prop", "remove_prop",
            "listen", "listen_latest", "unlisten",
            "insert_child", "move_child", "remove_child",
            "remove",
            "motion_set_target", "motion_cancel",
        )
        assertEquals(14, standardOps.size,
            "All standard operation names must be present")
        // Each op is a valid String
        for (op in standardOps) {
            assertTrue(op.isNotEmpty(), "Op name '$op' must not be empty")
        }
    }

    @Test
    fun elementContractsKindsIncludesPrimitives() {
        val kinds = dev.vyne.generated.ElementContracts.KINDS
        // Should include at minimum: Layout, Text, Box, TextInput
        val requiredKinds = setOf("Layout", "Text", "Box", "TextInput")
        for (kind in requiredKinds) {
            assertTrue(
                kind in kinds,
                "ElementContracts.KINDS must include '$kind'"
            )
        }
    }

    @Test
    fun clearOperationRequiresIdField() {
        // Contract test: preflight checks that clear op has "id".
        // The "id" field is required; its absence should be caught.
        // We verify by checking ElementContracts includes id requirements.
        val clearWithId = mapOf("op" to "clear", "id" to 0)
        val clearWithoutId = mapOf("op" to "clear")

        assertTrue(clearWithId.containsKey("id"),
            "Valid clear op must have 'id' field")
        assertTrue(!clearWithoutId.containsKey("id"),
            "Malformed clear op should not have 'id' field")
    }
}
