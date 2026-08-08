from __future__ import annotations

import json

from vyne.direct_transport import DirectTransport


class RecordingHost:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def __getattr__(self, name: str):
        def record(*args: object) -> None:
            self.calls.append((name, *args))

        return record


def transport_calls(host: RecordingHost):
    """Exclude the one-time session-publish call (design-pattern #1)."""
    return [call for call in host.calls if call[0] != "setSessionId"]


def test_property_only_commit_crosses_java_boundary_once() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    message = {
        "type": "commit",
        "revision": 7,
        "ops": [
            {"op": "set_prop", "id": 2, "name": "text", "value": "first"},
            {"op": "set_prop", "id": 3, "name": "enabled", "value": False},
            {"op": "set_prop", "id": 4, "name": "count", "value": 11},
        ],
    }
    transport.send(message)

    assert len(transport_calls(host)) == 1
    call = transport_calls(host)[0]
    assert call[0] == "commitPropBatch"
    assert call[1] == 7
    assert call[2] == [2, 3, 4]
    assert call[3] == ["text", "enabled", "count"]
    assert call[4] == bytes([4, 1, 2])
    assert call[5] == [0, 11]
    assert call[7] == ["first"]
    assert transport.send_count == 1
    assert transport.latest is message


def test_general_property_batch_keeps_typed_value_columns() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    transport.send(
        {
            "type": "commit",
            "revision": 8,
            "ops": [
                {"op": "set_prop", "id": 1, "name": "empty", "value": None},
                {"op": "set_prop", "id": 2, "name": "checked", "value": True},
                {"op": "set_prop", "id": 3, "name": "count", "value": -4},
                {"op": "set_prop", "id": 4, "name": "opacity", "value": 0.5},
                {
                    "op": "set_prop",
                    "id": 5,
                    "name": "metadata",
                    "value": {"items": ("a", "b")},
                },
            ],
        }
    )

    assert len(transport_calls(host)) == 1
    call = transport_calls(host)[0]
    assert call[0] == "commitPropBatch"
    assert call[1] == 8
    assert call[2] == [1, 2, 3, 4, 5]
    assert call[3] == ["empty", "checked", "count", "opacity", "metadata"]
    assert call[4] == bytes([0, 1, 2, 3, 5])
    assert call[5] == [1, -4]
    assert call[6] == [0.5]
    assert json.loads(call[7][0]) == {"items": ["a", "b"]}


def test_initial_create_units_are_sent_as_one_typed_mount() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    transport.send(
        {
            "type": "commit",
            "revision": 1,
            "ops": [
                {"op": "create", "id": 1, "kind": "Layout"},
                {
                    "op": "set_props",
                    "id": 1,
                    "props": {"orientation": "vertical"},
                },
                {"op": "create", "id": 2, "kind": "Text"},
                {
                    "op": "set_props",
                    "id": 2,
                    "props": {"text": "hello", "metadata": {"source": "test"}},
                },
                {"op": "insert_child", "parent": 1, "child": 2, "index": 0},
                {"op": "insert_child", "parent": 0, "child": 1, "index": 0},
            ],
        }
    )

    assert [call[0] for call in transport_calls(host)] == ["commitMountNodes"]
    mount = transport_calls(host)[0]
    assert mount[1] == 1
    assert mount[2] == [1, 2]
    assert mount[3] == ["Layout", "Text"]
    assert mount[4] == [1, 2]
    assert mount[5] == ["orientation", "text", "metadata"]
    assert mount[6] == bytes([4, 4, 5])
    assert json.loads(mount[9][2]) == {"source": "test"}
    assert mount[10] == [0, 1]
    assert mount[11] == bytes([0, 1])
    assert mount[12] == [0, 0]
    assert mount[13] == [0]
    assert mount[14] == [1]
    assert mount[15] == [0]
    assert mount[16:] == ([], [], [], b"")


def test_complete_mount_batches_listener_registration() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    transport.send(
        {
            "type": "commit",
            "revision": 2,
            "ops": [
                {"op": "create", "id": 1, "kind": "Text"},
                {"op": "set_props", "id": 1, "props": {"text": "hello"}},
                {"op": "insert_child", "parent": 0, "child": 1, "index": 0},
                {
                    "op": "listen_latest",
                    "id": 1,
                    "event": "click",
                    "handler": 7,
                },
            ],
        }
    )

    assert len(transport_calls(host)) == 1
    mount = transport_calls(host)[0]
    assert mount[0] == "commitMountNodes"
    assert mount[16] == [1]
    assert mount[17] == ["click"]
    assert mount[18] == [7]
    assert mount[19] == bytes([1])


def test_dense_string_updates_use_the_compact_direct_call() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    transport.send(
        {
            "type": "commit",
            "revision": 8,
            "ops": [
                {"op": "set_prop", "id": 20, "name": "text", "value": "a"},
                {"op": "set_prop", "id": 21, "name": "text", "value": "b"},
                {"op": "set_prop", "id": 22, "name": "text", "value": "c"},
            ],
        }
    )

    assert transport_calls(host) == [
        ("commitContiguousStringPropBatch", 8, 20, "text", ["a", "b", "c"])
    ]


def test_single_operations_keep_the_readable_direct_methods() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    transport.send(
        {
            "type": "commit",
            "revision": 3,
            "ops": [
                {"op": "remove_prop", "id": 8, "name": "text"},
                {"op": "remove_child", "parent": 1, "child": 8},
                {"op": "remove", "id": 9},
            ],
        }
    )

    assert [call[0] for call in transport_calls(host)] == [
        "beginCommit",
        "removeProp",
        "removeChild",
        "remove",
        "finishCommit",
    ]


def test_scroll_command_uses_typed_host_method() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    transport.send({
        "type": "commit",
        "revision": 4,
        "ops": [{
            "op": "scroll_to",
            "id": 8,
            "offset_x": 0,
            "offset_y": 240.5,
            "animated": True,
        }],
    })

    assert transport_calls(host) == [
        ("beginCommit", 4),
        ("scrollTo", 8, 0.0, 240.5, True),
        ("finishCommit",),
    ]


def test_motion_operations_use_typed_host_methods() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    transport.send(
        {
            "type": "commit",
            "revision": 9,
            "ops": [
                {
                    "op": "motion_set_target",
                    "animation_id": 12,
                    "slot_key": "view:5:slot:circle:cx",
                    "node_id": 5,
                    "property": "cx",
                    "slot_id": "circle",
                    "targets": [120.0, 140.0],
                    "from_value": 80.0,
                    "spec_type": "spring",
                    "stiffness": 240.0,
                    "damping_ratio": 0.7,
                    "rest_value_threshold": 0.02,
                    "rest_velocity_threshold": 0.03,
                    "retarget": "maintain_velocity",
                },
                {
                    "op": "motion_cancel",
                    "animation_id": 12,
                    "slot_key": "view:5:slot:circle:cx",
                },
                {
                    "op": "motion_driver_set_target",
                    "animation_id": 13,
                    "driver_id": 7,
                    "node_id": 5,
                    "property": "translation_x",
                    "targets": [0.5, 1.0],
                    "spec_type": "tween",
                    "duration_ms": 180,
                    "easing": "ease_in_out",
                    "retarget": "restart",
                },
                {
                    "op": "motion_driver_cancel",
                    "animation_id": 13,
                    "driver_id": 7,
                },
            ],
        }
    )

    assert transport_calls(host) == [
        ("beginCommit", 9),
        (
            "motionSetTarget",
            12,
            "view:5:slot:circle:cx",
            5,
            "cx",
            [120.0, 140.0],
            "circle",
            "spring",
            80.0,
            300,
            "ease_out",
            0.7,
            240.0,
            0.02,
            0.03,
            "maintain_velocity",
        ),
        ("motionCancel", 12, "view:5:slot:circle:cx"),
        (
            "motionDriverSetTarget",
            13,
            7,
            5,
            "translation_x",
            [0.5, 1.0],
            "tween",
            None,
            180,
            "ease_in_out",
            0.8,
            380.0,
            0.01,
            0.01,
            "restart",
        ),
        ("motionDriverCancel", 13, 7),
        ("finishCommit",),
    ]
