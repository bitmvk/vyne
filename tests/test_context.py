from __future__ import annotations

import asyncio
import inspect
import unittest

from vyne import AppContext, LaunchData, Text, state
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


class AppContextTests(unittest.TestCase):
    def _context_runtime(self, app):
        runtime = Runtime(app, transport=MemoryTransport())
        runtime.set_context_root(LaunchData(sequence=1, extras={"route": "x"}))
        runtime.mount()
        return runtime

    def test_context_carries_launch_and_stable_app_state(self) -> None:
        observed: list[tuple[int, str]] = []

        def app(context: AppContext):
            observed.append((context.launch.sequence, context.app_state.current))
            return Text(text=str(context.launch.sequence))

        runtime = self._context_runtime(app)
        first_state = next(obs[1] for obs in observed)
        self.assertEqual(first_state, "active")

        runtime.update_root_arguments(
            runtime.build_root_context(LaunchData(sequence=2))
        )
        self.assertEqual(observed[-1][0], 2)
        # The app_state object identity is stable across launches.
        self.assertEqual(observed[-1][1], observed[0][1])

    def test_app_state_subscription_fires_immediately(self) -> None:
        received: list[str] = []

        def app(context: AppContext):
            context.app_state.on_change(received.append)
            return Text(text="x")

        runtime = self._context_runtime(app)
        self.assertEqual(received, ["active"])

    def test_app_state_transitions_are_ordered_and_deduplicated(self) -> None:
        received: list[str] = []

        def app(context: AppContext):
            context.app_state.on_change(received.append)
            return Text(text="x")

        runtime = self._context_runtime(app)
        received.clear()

        runtime.handle_app_state("background")
        runtime.handle_app_state("background")
        runtime.handle_app_state("active")
        runtime.handle_app_state("inactive")

        self.assertEqual(received, ["background", "active", "inactive"])
        self.assertEqual(runtime.current_app_state, "inactive")

    def test_app_state_subscription_dispose(self) -> None:
        received: list[str] = []
        holder: dict[str, object] = {}

        def app(context: AppContext):
            holder["dispose"] = context.app_state.on_change(received.append)
            return Text(text="x")

        runtime = self._context_runtime(app)
        runtime.handle_app_state("background")
        holder["dispose"]()  # type: ignore[operator]
        runtime.handle_app_state("active")

        self.assertEqual(received, ["active", "background"])
        self.assertEqual(runtime.current_app_state, "active")

    def test_app_state_handler_can_be_async(self) -> None:
        received: list[str] = []

        async def handler(state):
            received.append(state)

        def app(context: AppContext):
            context.app_state.on_change(handler)
            return Text(text="x")

        runtime = self._context_runtime(app)
        runtime.wait_for_async_callbacks(2.0)
        self.assertEqual(received, ["active"])
        result = runtime.handle_app_state("background")
        if inspect.isawaitable(result):
            runtime._async_callbacks.schedule(result, None)
        runtime.wait_for_async_callbacks(2.0)
        self.assertEqual(received, ["active", "background"])

    def test_invalid_state_is_ignored(self) -> None:
        def app(context: AppContext):
            return Text(text="x")

        runtime = self._context_runtime(app)
        runtime.handle_app_state("sideways")
        self.assertEqual(runtime.current_app_state, "active")


if __name__ == "__main__":
    unittest.main()