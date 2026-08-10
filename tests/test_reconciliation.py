"""Tests for core reconciliation (CORE-01) and render-phase mutation guard.

Retained scope after consolidation:
- Runtime-level unkeyed position matching
- Runtime-level randomized keyed permutations
- Mixed tree + animation in one ordered commit (SCHED-01)
- Nested render-phase mutation detection (SCHED-03)
- Caught render-phase mutation leaves state unchanged (SCHED-03)

Weak duplicates of the reconcile planner's exhaustive oracle and of the
acknowledgement-map / pass-guard / publication coverage in
``test_commit_coordinator``, ``test_framework``, ``test_runtime_caveats``,
and ``test_publication_faults`` were removed.
"""

from __future__ import annotations

import random
import unittest

from vyne import Column, Text, component, state
from vyne.runtime import Runtime
from vyne.scheduler import RenderPhaseMutationError
from vyne.transport import MemoryTransport

from tests.support.runtime_helpers import (
    dispatch_native_event,
    find_listeners as _listeners,
)


class ReconciliationCoreTests(unittest.TestCase):
    """Runtime-level reconciliation of state-driven keyed/unkeyed children."""

    def test_unkeyed_children_match_by_position(self):
        """Unkeyed children match by position when both are unkeyed."""
        def App():
            items = state(["a", "b", "c"])
            return Column(*(
                Text(text=item) for item in items.value
            ))

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        root_scope = runtime._root_scope
        items_state = root_scope.hooks[0]
        items_state.set(["x", "b", "z"])

        # Position 1 ("b") should be kept in place; positions 0,2 are new.
        ops = runtime.latest_commit["ops"]
        self.assertNotIn("clear", [op.get("op") for op in ops])

    def test_randomized_keyed_permutations(self):
        """Seeded random lifecycle with keyed permutations (CORE-01).

        Each iteration: mount with one key set, then trigger a state change
        to a new key set on the same runtime, verifying the transition
        produces a valid commit with no errors.
        """
        rng = random.Random(42)
        key_pool = [f"k{i}" for i in range(5)]

        for iteration in range(50):
            old_keys = rng.sample(key_pool, rng.randint(0, 5))
            new_keys = rng.sample(key_pool, rng.randint(0, 5))

            def make_app(olist, nlist):
                def app():
                    keys_state = state(0)
                    current = olist if keys_state.value == 0 else nlist
                    return Column(
                        Text(text="trigger",
                             on_click=lambda e: keys_state.set(1)),
                        *(Text(text=k, key=k) for k in current),
                    )
                return app

            transport = MemoryTransport()
            runtime = Runtime(make_app(old_keys, new_keys), transport=transport)
            runtime.mount()

            commit = runtime.latest_commit
            self.assertNotIn("Error:", str(commit),
                            f"iter={iteration} old={old_keys}")
            self.assertIsNotNone(runtime._coordinator.accepted_root,
                                f"iter={iteration} old={old_keys}")

            # Trigger state change on the same runtime.
            click_listeners = _listeners(runtime.latest_commit, "click")
            if click_listeners:
                dispatch_native_event(runtime, click_listeners[0])

                commit2 = runtime.latest_commit
                self.assertNotIn("Error:", str(commit2),
                                f"iter={iteration} old={old_keys} new={new_keys}")
                self.assertIsNotNone(runtime._coordinator.accepted_root,
                                    f"iter={iteration} old={old_keys} new={new_keys}")


class AnimationOnlyCommitTests(unittest.TestCase):
    """SCHED-01: Tree + animation ops keep one ordered commit."""

    def test_mixed_tree_and_animation_one_commit(self):
        """Mixed tree+animation produces one ordered commit."""
        from vyne import animate

        def App():
            count = state(0)
            return Text(
                text=f"Clicks: {count.value}",
                on_click=lambda event: (
                    count.set(count.value + 1),
                    animate(event.target, "alpha", to=0.5, duration=300,
                            easing="ease_out"),
                ),
            )

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        listener = _listeners(runtime.latest_commit, "click")[0]
        dispatch_native_event(runtime, listener)

        # One commit with set_prop + motion_set_target in order.
        ops = runtime.latest_commit["ops"]
        op_types = [op["op"] for op in ops]
        # set_prop (text) should come before the motion op.
        self.assertIn("set_prop", op_types)
        self.assertIn("motion_set_target", op_types)
        set_idx = op_types.index("set_prop")
        anim_idx = op_types.index("motion_set_target")
        self.assertLess(set_idx, anim_idx,
                        "Tree ops should precede animation ops")


class RenderPhaseMutationGuardTests(unittest.TestCase):
    """SCHED-03: Render-phase mutation guard."""

    def test_nested_component_render_mutation_detected(self):
        """State.set in nested component render is detected."""
        @component
        def Child():
            val = state(0)
            val.set(1)  # Mutation during render.
            return Text(text=str(val.value))

        def App():
            return Column(Child())

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        self.assertIsNone(runtime._coordinator.accepted_root)
        self.assertIn("State.set() called during render pass",
                      str(runtime.latest_commit))

    def test_state_value_unchanged_after_render_mutation_attempt(self):
        """SCHED-03: State value unchanged after failed mutation.

        When the user catches RenderPhaseMutationError, the state value
        remains unchanged because the exception was raised before the
        assignment.  The Runtime detects the caught exception via the
        pass guard (the set attempted to trigger a re-render, but was
        blocked before mutation).
        """
        def App():
            val = state(0)
            # This set should raise and NOT change val.
            try:
                val.set(1)
            except RenderPhaseMutationError:
                pass
            return Text(text=str(val.value))

        transport = MemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()

        # The guard raises before changing value, user catches it.
        # Render completes with value unchanged.
        self.assertIsNotNone(runtime._coordinator.accepted_root)
        # Value should be "0" (unchanged).
        text_props = [
            op["props"]
            for op in runtime.latest_commit["ops"]
            if op.get("op") == "set_props"
            and op.get("props", {}).get("text") == "0"
        ]
        self.assertTrue(text_props,
                       f"Expected text='0', got: {text_props}")


if __name__ == "__main__":
    unittest.main()
