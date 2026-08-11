package dev.vyne

import dev.vyne.generated.ElementContracts
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Verifies the regenerated Kotlin contracts and the applicator table cover
 * the private virtual-list sticky props: Box-only, absent from the public
 * generic surface, and registered with mechanical set/remove applicators so
 * the renderer can apply, reset, and roll back them through the existing
 * property lifecycle.
 */
class VirtualStickyContractTest {

    private val stickyProps = listOf(
        "_virtual_content",
        "_virtual_content_width",
        "_virtual_content_height",
        "_virtual_sticky_edge",
        "_virtual_sticky_boundary_start",
        "_virtual_sticky_boundary_end",
    )

    @Test
    fun contractsIncludeStickyPropsOnBoxOnly() {
        val box = ElementContracts.ALL_PROPS_BY_KIND.getValue("Box")
        for (name in stickyProps) {
            assertTrue(name in box, "$name missing from Box contract")
        }
        for (kind in ElementContracts.KINDS) {
            if (kind == "Box") continue
            val props = ElementContracts.ALL_PROPS_BY_KIND.getValue(kind)
            for (name in stickyProps) {
                assertFalse(
                    name in props,
                    "$name leaked into $kind contract",
                )
            }
        }
    }

    @Test
    fun stickyPropsAreNotPublicGenericProps() {
        for (name in stickyProps) {
            assertFalse(
                name in ElementContracts.GENERIC_PROPS,
                "$name must stay out of the public generic surface",
            )
        }
    }

    @Test
    fun applicatorsAreRegisteredForBox() {
        for (name in stickyProps) {
            assertNotNull(PropertyTable.get(name, "Box"), "no applicator for $name")
        }
        // Not applicable to other kinds: the applicator table must not expose
        // them there.
        for (kind in ElementContracts.KINDS) {
            if (kind == "Box") continue
            for (name in stickyProps) {
                assertNull(PropertyTable.get(name, kind), "$name must not apply to $kind")
            }
        }
    }

    @Test
    fun translationApplicatorsTrackNaturalTranslation() {
        // The PropertyTable entries exist; the RoundedFrameLayout binding is
        // exercised on device, but the applicator wiring is present.
        assertNotNull(PropertyTable.get("translation_x", "Box"))
        assertNotNull(PropertyTable.get("translation_y", "Box"))
    }
}
