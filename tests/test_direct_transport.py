from __future__ import annotations

import json

from vyne.direct_transport import DirectTransport
from vyne.values import FrozenMap


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


def commit_payload(host: RecordingHost) -> dict:
    """Decode the JSON document from the single commitJson crossing."""
    call = transport_calls(host)[0]
    assert call[0] == "commitJson"
    return json.loads(call[1])


def test_every_commit_is_one_json_bridge_call() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    transport.send(
        {
            "type": "commit",
            "revision": 7,
            "ops": [
                {"op": "set_prop", "id": 2, "name": "text", "value": "first"},
                {"op": "set_prop", "id": 3, "name": "enabled", "value": False},
                {"op": "set_prop", "id": 4, "name": "count", "value": 11},
                {"op": "scroll_to", "id": 8, "offset_x": 0, "offset_y": 240.5, "animated": True},
            ],
        }
    )

    assert len(transport_calls(host)) == 1
    assert transport_calls(host)[0][0] == "commitJson"
    payload = commit_payload(host)
    assert payload["revision"] == 7
    # Ordering is preserved exactly as Python emitted the ops.
    assert [op["op"] for op in payload["ops"]] == [
        "set_prop",
        "set_prop",
        "set_prop",
        "scroll_to",
    ]
    assert transport.send_count == 1
    assert transport.latest is not None
    assert transport.latest["revision"] == 7


def test_values_survive_the_json_round_trip() -> None:
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
                    "value": FrozenMap((("items", ("a", "b")),)),
                },
            ],
        }
    )

    ops = commit_payload(host)["ops"]
    assert [op["name"] for op in ops] == [
        "empty",
        "checked",
        "count",
        "opacity",
        "metadata",
    ]
    assert ops[0]["value"] is None
    assert ops[1]["value"] is True
    assert ops[2]["value"] == -4
    assert ops[3]["value"] == 0.5
    assert ops[4]["value"] == {"items": ["a", "b"]}


def test_mounts_travel_as_one_json_commit() -> None:
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
                {
                    "op": "listen_latest",
                    "id": 2,
                    "event": "click",
                    "handler": 7,
                },
            ],
        }
    )

    assert len(transport_calls(host)) == 1
    payload = commit_payload(host)
    assert [op["op"] for op in payload["ops"]] == [
        "create",
        "set_props",
        "create",
        "set_props",
        "insert_child",
        "insert_child",
        "listen_latest",
    ]
    assert payload["ops"][3]["props"] == {
        "text": "hello",
        "metadata": {"source": "test"},
    }


def test_motion_operations_travel_unchanged() -> None:
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

    ops = commit_payload(host)["ops"]
    assert ops[0]["targets"] == [120.0, 140.0]
    assert ops[0]["spec_type"] == "spring"
    assert ops[2]["targets"] == [0.5, 1.0]
    assert ops[2]["duration_ms"] == 180
    assert [op["op"] for op in ops] == [
        "motion_set_target",
        "motion_cancel",
        "motion_driver_set_target",
        "motion_driver_cancel",
    ]


def test_session_identity_is_published_before_the_first_commit() -> None:
    host = RecordingHost()
    transport = DirectTransport(host, session_id="session-abc")

    transport.send({
        "type": "commit",
        "revision": 4,
        "ops": [{"op": "remove", "id": 9}],
    })

    assert host.calls[0] == ("setSessionId", "session-abc")
    assert transport_calls(host)[0][0] == "commitJson"


def test_send_rejects_non_commit_messages() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    try:
        transport.send({"type": "event", "seq": 1})
    except ValueError as error:
        assert "commit" in str(error)
    else:
        raise AssertionError("send() should reject non-commit messages")


def test_send_rejects_non_integer_revisions() -> None:
    for revision in ("7", True):
        host = RecordingHost()
        transport = DirectTransport(host)

        try:
            transport.send({"type": "commit", "revision": revision, "ops": []})
        except TypeError as error:
            assert "revision" in str(error)
        else:
            raise AssertionError("send() should reject a non-integer revision")


def test_send_rejects_non_finite_floats() -> None:
    host = RecordingHost()
    transport = DirectTransport(host)

    try:
        transport.send({
            "type": "commit",
            "revision": 5,
            "ops": [
                {"op": "set_prop", "id": 1, "name": "opacity", "value": float("nan")}
            ],
        })
    except ValueError:
        pass
    else:
        raise AssertionError("send() should reject non-finite values")
