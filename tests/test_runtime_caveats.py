"""Caveat tests for Runtime lifecycle, dispatch, and recovery edges.

Focuses on the guards that keep a broken or hostile event stream from
corrupting accepted state: malformed input discard, stale listener
identity, in-flight gating, fault bounding, and disposal semantics.
"""

from __future__ import annotations

import unittest

from vyne import Box, Text, animate, state
from vyne.recovery import RecoveryState
from vyne.refs import Ref
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport

from tests.support.runtime_helpers import (
    SilentTransport,
    dispatch_native_event,
    first_listener,
)


# ---------------------------------------------------------------------------
# Scheduler/recovery semantics: test_runtime_caveats.py uses SilentTransport
# and native event dispatch heavily.
# ---------------------------------------------------------------------------


def _system_apply(revision: int, result: str = "ok") -> dict:
    return {
        "type": "event", "target": 0, "event": "__vyne_system__",
        "handler": 0,
        "payload": {
            "type": "native_apply_result", "result": result,
            "revision": revision, "session": "vyne-runtime-session",
        },
    }


class DisposalTests(unittest.TestCase):
    def test_dispose_is_idempotent(self):
        runtime = Runtime(lambda: Text(text="x"), transport=MemoryTransport())
        runtime.mount()
        runtime.dispose()
        runtime.dispose()  # second call must not raise
        self.assertEqual(runtime.recovery_state, RecoveryState.DISPOSED)

    def test_request_render_after_dispose_is_noop(self):
        transport = MemoryTransport()
        runtime = Runtime(lambda: Text(text="x"), transport=transport)
        runtime.mount()
        sent = transport.send_count
        runtime.dispose()
        runtime.request_render()
        self.assertEqual(transport.send_count, sent)

    def test_dispose_invalidates_refs(self):
        ref = Ref()
        runtime = Runtime(lambda: Box(ref=ref), transport=MemoryTransport())
        runtime.mount()
        self.assertIsNotNone(ref.current)
        runtime.dispose()
        self.assertIsNone(ref.current)

    def test_ack_and_failure_after_dispose_ignored(self):
        runtime = Runtime(lambda: Text(text="x"), transport=MemoryTransport())
        runtime.mount()
        runtime.dispose()
        runtime.acknowledge_native_apply(1)
        runtime.report_native_failure("late", revision=1)
        self.assertEqual(runtime.recovery_state, RecoveryState.DISPOSED)


class MalformedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        self.runtime = Runtime(lambda: Text(text="stable"), transport=self.transport)
        self.runtime.mount()
        self.baseline_revision = self.runtime.revision

    def test_garbage_string_discarded(self):
        self.runtime.dispatch_event("not json at all {{{")
        self.assertIsNotNone(self.runtime._coordinator.accepted_root)

    def test_binary_garbage_discarded(self):
        self.runtime.dispatch_event(b"\x00\x01\x02\x03")
        self.assertIsNotNone(self.runtime._coordinator.accepted_root)

    def test_non_dict_batch_entries_ignored(self):
        sent = self.transport.send_count
        self.runtime.dispatch_events(["nope", 42])  # type: ignore[list-item]
        self.assertEqual(self.transport.send_count, sent)

    def test_empty_batch_ignored(self):
        sent = self.transport.send_count
        self.runtime.dispatch_events([])
        self.assertEqual(self.transport.send_count, sent)

    def test_commit_message_not_dispatched_as_event(self):
        sent = self.transport.send_count
        self.runtime.dispatch_event({
            "type": "commit", "revision": 99, "ops": [],
        })
        self.assertEqual(self.transport.send_count, sent)

    def test_event_for_unknown_target_ignored(self):
        sent = self.transport.send_count
        self.runtime.dispatch_event({
            "type": "event", "seq": 1, "target": 999_999,
            "event": "click", "handler": 1, "payload": {},
        })
        self.assertEqual(self.transport.send_count, sent)

    def test_event_with_stale_handler_id_ignored(self):
        """A delayed event must never bind to a replacement callback."""
        calls: list[int] = []

        def App():
            return Text(text="b", on_click=lambda e: calls.append(e.handler))

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        listener = next(
            op for op in transport.latest["ops"]
            if op["op"] == "listen" and op["event"] == "click"
        )
        # Correct target, wrong handler id — must be dropped.
        runtime.dispatch_event({
            "type": "event", "seq": 1, "target": listener["id"],
            "event": "click", "handler": listener["handler"] + 1000,
            "payload": {},
        })
        self.assertEqual(calls, [])


class AcknowledgementEdgeTests(unittest.TestCase):
    def test_stale_and_malformed_acks_ignored(self):
        transport = SilentTransport()
        runtime = Runtime(lambda: Text(text="x"), transport=transport)
        runtime.mount()
        self.assertEqual(runtime.recovery_state, RecoveryState.AWAITING_APPLY)
        # Wrong revision, negative, and bool acks are all ignored.
        runtime.acknowledge_native_apply(999)
        runtime.acknowledge_native_apply(-1)
        runtime.acknowledge_native_apply(True)  # type: ignore[arg-type]
        self.assertEqual(runtime.recovery_state, RecoveryState.AWAITING_APPLY)
        # Exact revision promotes.
        runtime.acknowledge_native_apply(1)
        self.assertEqual(runtime.recovery_state, RecoveryState.SYNCED)

    def test_system_event_with_wrong_session_ignored(self):
        transport = SilentTransport()
        runtime = Runtime(lambda: Text(text="x"), transport=transport)
        runtime.mount()
        event = _system_apply(1)
        event["payload"]["session"] = "someone-else"
        runtime.dispatch_event(event)
        self.assertEqual(runtime.recovery_state, RecoveryState.AWAITING_APPLY)

    def test_failure_for_non_inflight_revision_ignored(self):
        transport = SilentTransport()
        runtime = Runtime(lambda: Text(text="x"), transport=transport)
        runtime.mount()
        runtime.report_native_failure("bogus", revision=77)
        self.assertEqual(runtime.recovery_state, RecoveryState.AWAITING_APPLY)


class RecoveryFlowTests(unittest.TestCase):
    def test_known_rejection_preserves_accepted_tree(self):
        transport = SilentTransport()
        count_text = {"value": "0"}
        count_cell = {}

        def App():
            count = state(0)
            count_cell["value"] = count
            count_text["value"] = str(count.value)
            return Text(
                text=f"n={count.value}",
                on_click=lambda e: count.set(count.value + 1),
            )

        runtime = Runtime(App, transport=transport)
        runtime.mount()
        runtime.acknowledge_native_apply(1)
        accepted_before = runtime._coordinator.accepted_root

        listener = first_listener(transport.latest, "click")
        dispatch_native_event(runtime, listener)
        # A new commit is in flight; native rejects it as a known failure.
        self.assertEqual(runtime.recovery_state, RecoveryState.AWAITING_APPLY)
        inflight = runtime._coordinator.in_flight_revision
        runtime.report_native_failure("rejected_known", revision=inflight)
        self.assertEqual(runtime.recovery_state, RecoveryState.SYNCED)
        # The accepted tree is unchanged and state was rolled back.
        self.assertIs(runtime._coordinator.accepted_root, accepted_before)
        self.assertEqual(count_cell["value"].value, 0)
        self.assertEqual(runtime._root_scope.output.props["text"], "n=0")

    def test_unknown_native_state_triggers_snapshot_commit(self):
        transport = SilentTransport()
        runtime = Runtime(lambda: Text(text="x"), transport=transport)
        runtime.mount()
        sent = len(transport.messages)
        runtime.report_native_failure("unknown", revision=1, unknown=True)
        # The desired state is re-sent immediately as a full snapshot
        # (clear + rebuild), and the runtime awaits its acknowledgement.
        self.assertGreater(len(transport.messages), sent)
        self.assertEqual(runtime.recovery_state, RecoveryState.AWAITING_APPLY)
        ops = transport.latest["ops"]
        self.assertEqual(ops[0]["op"], "clear")
        self.assertIn("create", [op["op"] for op in ops])

    def test_consecutive_faults_trip_terminal_faulted(self):
        transport = MemoryTransport()
        attempts = {"n": 0}

        def App():
            attempts["n"] += 1
            raise RuntimeError("always broken")

        runtime = Runtime(App, transport=transport)
        runtime.mount()
        # Cold-start render fails once: error commit, NEEDS_RESET.
        self.assertEqual(runtime.recovery_state, RecoveryState.NEEDS_RESET)
        # Keep poking renders; each fails until the fault bound trips.
        for _ in range(runtime._max_consecutive_faults + 2):
            runtime.request_render()
        self.assertEqual(runtime.recovery_state, RecoveryState.FAULTED)
        self.assertGreater(attempts["n"], 1)  # each poke really re-rendered
        # Once FAULTED, further failures do not emit more error commits.
        sends_at_fault = transport.send_count
        runtime.request_render()
        self.assertEqual(transport.send_count, sends_at_fault)

    def test_error_commit_uses_supported_kinds_only(self):
        transport = MemoryTransport()

        def App():
            raise RuntimeError("kaboom")

        runtime = Runtime(App, transport=transport)
        runtime.mount()
        kinds = [
            op["kind"] for op in transport.latest["ops"]
            if op["op"] == "create"
        ]
        self.assertEqual(kinds, ["Layout", "Text"])


class HookContractTests(unittest.TestCase):
    def test_state_outside_render_raises(self):
        runtime = Runtime(lambda: Text(text="x"), transport=MemoryTransport())
        with self.assertRaisesRegex(RuntimeError, "rendering"):
            runtime.use_state(0)

    def test_component_outside_render_raises(self):
        runtime = Runtime(lambda: Text(text="x"), transport=MemoryTransport())
        with self.assertRaisesRegex(RuntimeError, "while rendering"):
            runtime.render_component(lambda: Text(text="x"), (), {})

    def test_state_mutation_during_render_emits_error_commit(self):
        def App():
            bad = state(0)
            bad.set(bad.value + 1)  # illegal during render
            return Text(text="x")

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        # Cold-start failure: error commit with fallback screen.
        texts = [
            op["props"].get("text", "")
            for op in transport.latest["ops"] if op["op"] == "set_props"
        ]
        self.assertTrue(any("render pass" in t for t in texts))


class AnimationOnlyCommitTests(unittest.TestCase):
    def test_animation_only_commit_carries_origin_seq(self):
        transport = MemoryTransport()

        def App():
            return Text(text="x", on_click=lambda e: animate(e.target, "alpha", to=0.5))

        runtime = Runtime(App, transport=transport)
        runtime.mount()
        listener = first_listener(transport.latest, "click")
        dispatch_native_event(runtime, listener, seq=42)
        commit = transport.latest
        self.assertEqual(commit.get("origin_event_seq"), 42)
        self.assertEqual(
            [op["op"] for op in commit["ops"]], ["motion_set_target"],
        )

    def test_animation_only_commit_gated_while_in_flight(self):
        transport = SilentTransport()

        clicks = {"n": 0}

        def App():
            count = state(0)

            def on_click(event):
                clicks["n"] += 1
                if clicks["n"] == 1:
                    count.set(count.value + 1)
                else:
                    animate(event.target, "alpha", to=0.5)

            return Text(text=f"{count.value}", on_click=on_click)

        runtime = Runtime(App, transport=transport)
        runtime.mount()
        runtime.acknowledge_native_apply(1)  # mount accepted; SYNCED
        listener = first_listener(transport.latest, "click")

        def click(seq: int) -> None:
            dispatch_native_event(runtime, listener, seq=seq)

        # Tree-changing click: commit goes out and stays in flight.
        click(seq=1)
        self.assertEqual(runtime.recovery_state, RecoveryState.AWAITING_APPLY)
        inflight = runtime._coordinator.in_flight_revision

        # Animation-only click while in flight: gated, nothing sent.
        sent = len(transport.messages)
        click(seq=2)
        self.assertEqual(len(transport.messages), sent)
        self.assertEqual(len(runtime._anim_pending), 1)

        # Acknowledging the in-flight commit flushes the deferred
        # animation as its own animation-only commit (SCHED-01).
        runtime.acknowledge_native_apply(inflight)
        self.assertGreater(len(transport.messages), sent)
        self.assertEqual(runtime._anim_pending, [])
        self.assertEqual(
            [op["op"] for op in transport.latest["ops"]],
            ["motion_set_target"],
        )


if __name__ == "__main__":
    unittest.main()


class InputEqualityTests(unittest.TestCase):
    """Component input equality contract (structural callable comparison)."""

    def test_inline_lambdas_with_identical_code_are_equal(self) -> None:
        from vyne.runtime import _inputs_equal

        def make() -> object:
            # The same lambda expression re-evaluated shares one code object.
            return lambda item, index: item

        first = make()
        second = make()
        assert first.__code__ is second.__code__
        assert _inputs_equal(first, second)

    def test_lambdas_capturing_different_objects_are_not_equal(self) -> None:
        from vyne.runtime import _inputs_equal

        captured_a = object()
        captured_b = object()
        first = lambda: captured_a  # noqa: E731
        second = lambda: captured_b  # noqa: E731
        assert not _inputs_equal(first, second)
        assert _inputs_equal(first, first)

    def test_bound_methods_require_the_same_receiver(self) -> None:
        from vyne.runtime import _inputs_equal

        class Receiver:
            def __init__(self, value: int) -> None:
                self.value = value

            def render(self, item) -> int:
                return item + self.value

        receiver_a = Receiver(1)
        receiver_b = Receiver(2)
        assert _inputs_equal(receiver_a.render, receiver_a.render)
        assert not _inputs_equal(receiver_a.render, receiver_b.render)

    def test_containers_compare_structurally(self) -> None:
        from vyne.runtime import _inputs_equal

        assert _inputs_equal((1, [2, (3,)], {"k": "v"}), (1, [2, (3,)], {"k": "v"}))
        assert not _inputs_equal((1, [2, (3,)], {"k": "v"}), (1, [2, (3,)], {"k": "w"}))
        assert _inputs_equal({"a": (1, 2)}, {"a": (1, 2)})
        assert not _inputs_equal({"a": (1, 2)}, {"a": (1, 3)})

    def test_frozen_map_inputs_compare_by_value(self) -> None:
        from vyne.runtime import _inputs_equal
        from vyne.values import FrozenMap

        props_a = FrozenMap({"overscan": 1.0, "axis": "vertical"}.items())
        props_b = FrozenMap({"overscan": 1.0, "axis": "vertical"}.items())
        props_c = FrozenMap({"overscan": 2.0, "axis": "vertical"}.items())
        assert _inputs_equal((props_a,), (props_b,))
        assert not _inputs_equal((props_a,), (props_c,))

    def test_equality_errors_are_conservative(self) -> None:
        from vyne.runtime import _inputs_equal

        class Explosive:
            def __eq__(self, other: object) -> bool:
                raise RuntimeError("boom")

        assert not _inputs_equal(Explosive(), Explosive())

    def test_different_callable_kinds_are_conservative(self) -> None:
        from vyne.runtime import _inputs_equal
        import functools

        def plain() -> None:
            return None

        partial = functools.partial(plain)
        assert _inputs_equal(partial, partial)
        assert not _inputs_equal(plain, partial)
