from __future__ import annotations

import json
from pathlib import Path

import pytest
from vyne._lists.host_contract import (
    INTERACTIVE_SCROLLBAR_MIN_THUMB,
    INTERACTIVE_SCROLLBAR_TOUCH_TARGET,
    INTERACTIVE_SCROLLBAR_VISUAL_THICKNESS,
    VIRTUAL_SCROLL_SEEK_EMIT_INTERVAL_MS,
    VIRTUAL_SCROLL_SEEK_MAX_RETRIES,
    VIRTUAL_SCROLL_SEEK_TARGET_TOLERANCE,
    VIRTUAL_SCROLL_SEEK_WATCHDOG_MS,
    ScrollHostMetrics,
    ScrollSeekEmission,
    VirtualScrollSeekReference,
    clamp_projected_offset,
    interactive_scrollbar_geometry,
    interactive_scrollbar_grab_offset,
    interactive_scrollbar_target,
    sticky_main_position,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "list_host_contract.json").read_text()
)


def test_contract_constants_match_fixture() -> None:
    constants = FIXTURE["constants"]
    assert constants["minimum_thumb_extent"] == INTERACTIVE_SCROLLBAR_MIN_THUMB
    assert constants["touch_target_extent"] == INTERACTIVE_SCROLLBAR_TOUCH_TARGET
    assert constants["visual_thumb_thickness"] == INTERACTIVE_SCROLLBAR_VISUAL_THICKNESS
    assert constants["seek_emit_interval_ms"] == VIRTUAL_SCROLL_SEEK_EMIT_INTERVAL_MS
    assert (
        constants["seek_target_tolerance_px"]
        == VIRTUAL_SCROLL_SEEK_TARGET_TOLERANCE
    )
    assert constants["seek_watchdog_ms"] == VIRTUAL_SCROLL_SEEK_WATCHDOG_MS
    assert constants["seek_max_retries"] == VIRTUAL_SCROLL_SEEK_MAX_RETRIES


@pytest.mark.parametrize("case", FIXTURE["sticky"], ids=lambda case: case["name"])
def test_sticky_reference_fixture(case: dict[str, object]) -> None:
    inputs = {
        name: value for name, value in case.items() if name not in {"name", "expected"}
    }
    assert sticky_main_position(**inputs) == pytest.approx(case["expected"])


@pytest.mark.parametrize("case", FIXTURE["scrollbar"], ids=lambda case: case["name"])
def test_interactive_scrollbar_reference_fixture(case: dict[str, object]) -> None:
    geometry = interactive_scrollbar_geometry(
        axis=case["axis"],
        viewport_extent=case["viewport_extent"],
        content_extent=case["content_extent"],
        scroll_offset=case["scroll_offset"],
        track_start=case["track_start"],
        track_extent=case["track_extent"],
    )
    expected = case["expected"]
    if expected is None:
        assert geometry is None
        return
    assert geometry is not None
    assert geometry.thumb_start == pytest.approx(expected["thumb_start"])
    assert geometry.thumb_extent == pytest.approx(expected["thumb_extent"])
    assert geometry.max_scroll == pytest.approx(expected["max_scroll"])
    grab_offset = case.get("grab_offset")
    if grab_offset is None:
        grab_offset = interactive_scrollbar_grab_offset(case["pointer"], geometry)
        assert grab_offset == pytest.approx(case["expected_grab_offset"])
    target = interactive_scrollbar_target(
        pointer_position=case["pointer"],
        grab_offset=grab_offset,
        geometry=geometry,
    )
    assert target == pytest.approx(case["expected_target"])


@pytest.mark.parametrize("case", FIXTURE["projection"], ids=lambda case: case["name"])
def test_projected_offset_fixture(case: dict[str, object]) -> None:
    assert clamp_projected_offset(
        case["projected_offset"],
        viewport_extent=case["viewport_extent"],
        content_extent=case["content_extent"],
    ) == pytest.approx(case["expected"])


def test_virtual_seek_reference_throttles_latest_and_retries_final() -> None:
    state = VirtualScrollSeekReference()
    assert state.update(100, 1_000, final=False) == ScrollSeekEmission(100, False)
    assert state.update(200, 1_010, final=False) is None
    assert state.provisional_target == 200
    assert state.update(300, 1_032, final=False) == ScrollSeekEmission(300, False)
    assert state.update(350, 1_033, final=True) == ScrollSeekEmission(350, True)
    assert state.watchdog(0) == ScrollSeekEmission(350, True)
    assert state.watchdog(0) == ScrollSeekEmission(350, True)
    assert state.watchdog(0) is None
    assert state.provisional_target is None


def test_virtual_seek_reference_matching_reveal_and_reset() -> None:
    state = VirtualScrollSeekReference()
    state.update(100, 0, final=False)
    state.update(200, 32, final=False)
    assert state.accept_reveal(100) is True
    assert state.provisional_target == 200
    # Any prepared older reveal is safe to accept, but it must not clear the
    # newest provisional target.
    assert state.accept_reveal(999) is True
    assert state.provisional_target == 200
    # One host pixel of dp round-trip drift still completes the latest seek.
    assert state.accept_reveal(201) is True
    assert state.provisional_target is None
    state.reset()
    assert state.display_target(7) == 7


def test_scroll_host_metrics_clamps_actual_and_projected_offsets() -> None:
    metrics = ScrollHostMetrics("vertical", 1000, 100, 600, 5000)
    assert metrics.offset == 500
    assert metrics.projected_offset == 500
    assert metrics.max_scroll == 500

    negative_projection = ScrollHostMetrics("vertical", 0, 100, 600, -50)
    assert negative_projection.projected_offset == 0


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ScrollHostMetrics("diagonal", 0, 1, 2, 0),
        lambda: interactive_scrollbar_geometry(
            axis="vertical",
            viewport_extent=-1,
            content_extent=10,
            scroll_offset=0,
        ),
        lambda: sticky_main_position(
            natural=0,
            extent=1,
            viewport_start=2,
            viewport_end=1,
            boundary_start=0,
            boundary_end=3,
            edge="start",
        ),
    ],
)
def test_reference_contract_rejects_malformed_inputs(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()
