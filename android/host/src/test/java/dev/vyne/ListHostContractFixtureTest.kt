package dev.vyne

import org.json.JSONObject
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ListHostContractFixtureTest {
    private val fixture: JSONObject by lazy {
        val stream = checkNotNull(javaClass.classLoader?.getResourceAsStream(
            "list_host_contract.json",
        )) { "shared list_host_contract.json fixture not found" }
        JSONObject(stream.bufferedReader().use { it.readText() })
    }

    @Test
    fun seekTimingConstantsMatchSharedPlatformFixture() {
        val constants = fixture.getJSONObject("constants")
        assertEquals(
            constants.getLong("seek_emit_interval_ms"),
            VIRTUAL_SCROLL_SEEK_EMIT_INTERVAL_MS,
        )
        assertEquals(
            constants.getLong("seek_watchdog_ms"),
            VIRTUAL_SCROLL_SEEK_WATCHDOG_MS,
        )
        assertEquals(
            constants.getInt("seek_max_retries"),
            VIRTUAL_SCROLL_SEEK_MAX_RETRIES,
        )
    }

    @Test
    fun interactiveScrollbarIsAHostScrollCapabilityOnly() {
        val contracts = dev.vyne.generated.ElementContracts.ALL_PROPS_BY_KIND
        for (kind in dev.vyne.generated.ElementContracts.KINDS) {
            if (kind == "Scroll" || kind == "HorizontalScroll") {
                assertTrue("interactive_scrollbar" in contracts.getValue(kind))
                assertNotNull(PropertyTable.get("interactive_scrollbar", kind))
            } else {
                assertFalse("interactive_scrollbar" in contracts.getValue(kind))
                assertNull(PropertyTable.get("interactive_scrollbar", kind))
            }
        }
    }

    @Test
    fun stickyMathMatchesSharedPlatformFixture() {
        val cases = fixture.getJSONArray("sticky")
        for (index in 0 until cases.length()) {
            val case = cases.getJSONObject(index)
            val edge = if (case.isNull("edge")) null else case.getString("edge")
            val actual = computeStickyMain(
                case.float("natural"),
                case.float("extent"),
                case.float("viewport_start"),
                case.float("viewport_end"),
                case.float("boundary_start"),
                case.float("boundary_end"),
                edge,
            )
            assertEquals(case.float("expected"), actual, 0.001f, case.getString("name"))
        }
    }

    @Test
    fun interactiveScrollbarMatchesSharedPlatformFixture() {
        val constants = fixture.getJSONObject("constants")
        val minimum = constants.float("minimum_thumb_extent")
        assertEquals(INTERACTIVE_SCROLLBAR_MIN_THUMB_DP, minimum, 0.001f)
        assertEquals(
            INTERACTIVE_SCROLLBAR_TOUCH_TARGET_DP,
            constants.float("touch_target_extent"),
            0.001f,
        )
        assertEquals(
            INTERACTIVE_SCROLLBAR_VISUAL_THICKNESS_DP,
            constants.float("visual_thumb_thickness"),
            0.001f,
        )
        assertEquals(
            VIRTUAL_SCROLL_SEEK_TARGET_TOLERANCE_PX,
            constants.getInt("seek_target_tolerance_px"),
        )
        val cases = fixture.getJSONArray("scrollbar")
        for (index in 0 until cases.length()) {
            val case = cases.getJSONObject(index)
            val geometry = InteractiveScrollbarMath.geometry(
                case.float("track_start"),
                case.float("track_extent"),
                case.float("viewport_extent"),
                case.float("content_extent"),
                case.float("scroll_offset"),
                minimum,
            )
            if (case.isNull("expected")) {
                assertNull(geometry, case.getString("name"))
                continue
            }
            checkNotNull(geometry)
            val expected = case.getJSONObject("expected")
            assertEquals(
                expected.float("thumb_start"),
                geometry.thumbStart,
                0.001f,
                case.getString("name"),
            )
            assertEquals(
                expected.float("thumb_extent"),
                geometry.thumbExtent,
                0.001f,
                case.getString("name"),
            )
            assertEquals(
                expected.float("max_scroll"),
                geometry.maxScroll,
                0.001f,
                case.getString("name"),
            )
            if (case.has("pointer")) {
                val grab = if (case.has("grab_offset")) {
                    case.float("grab_offset")
                } else {
                    InteractiveScrollbarMath.grabOffset(case.float("pointer"), geometry)
                        .also {
                            assertEquals(
                                case.float("expected_grab_offset"),
                                it,
                                0.001f,
                                case.getString("name"),
                            )
                        }
                }
                assertEquals(
                    case.float("expected_target"),
                    InteractiveScrollbarMath.targetOffset(
                        case.float("pointer"),
                        grab,
                        geometry,
                    ).toFloat(),
                    0.51f,
                    case.getString("name"),
                )
            }
        }
    }

    @Test
    fun androidSemanticExtentFailsBeforeMeasuredSizeTruncation() {
        val demoExtent = virtualContentExtentToPx(5_600_000, 2.625f)
        assertEquals(14_700_000, demoExtent)
        assertEquals(
            ANDROID_MEASURED_CONTENT_EXTENT_LIMIT_PX,
            virtualContentExtentToPx(
                ANDROID_MEASURED_CONTENT_EXTENT_LIMIT_PX,
                1f,
            ),
        )
        val error = assertFailsWith<IllegalArgumentException> {
            virtualContentExtentToPx(
                ANDROID_MEASURED_CONTENT_EXTENT_LIMIT_PX + 1L,
                1f,
            )
        }
        assertTrue(error.message.orEmpty().contains("segmented/rebased scrolling"))
    }

    @Test
    fun logicalScrollOffsetRoundTripsToNearestPixelAt420Dpi() {
        val density = 2.625f
        for (pixels in listOf(57, 61, 16_000_001)) {
            val logical = pixels / density
            assertEquals(pixels, logicalScrollOffsetToPx(logical, density))
        }
    }

    @Test
    fun projectionClampMatchesSharedPlatformFixture() {
        val cases = fixture.getJSONArray("projection")
        for (index in 0 until cases.length()) {
            val case = cases.getJSONObject(index)
            assertEquals(
                case.float("expected"),
                InteractiveScrollbarMath.clampProjectedOffset(
                    case.float("projected_offset"),
                    case.float("viewport_extent"),
                    case.float("content_extent"),
                ),
                0.001f,
                case.getString("name"),
            )
        }
    }

    private fun JSONObject.float(name: String): Float = getDouble(name).toFloat()
}
