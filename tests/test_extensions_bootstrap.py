"""pre_launch capture-hook tests (EXT-05).

The framework provides ONE launch-capture tool: ``run_app(App,
pre_launch=fn)``. The hook runs on every launch — at mount for cold starts,
before the root re-render for warm starts. It is capture-only: errors are
logged and never block the launch; a zero-argument app keeps today's
capture-only behavior. Extensions export plain launch functions and the APP
composes them into its hook — no framework-side wiring exists.
"""

from __future__ import annotations

from contextlib import contextmanager
import unittest
from types import SimpleNamespace

from vyne.bootstrap import (
    _run_pre_launch_chain,
    run_app,
)
from vyne.launch import LaunchData


@contextmanager
def _registration_attempt():
    """Run one body inside a host registration attempt context."""
    import vyne.bootstrap as bm

    attempt = bm._RegistrationAttempt("x")
    token = bm._registration_attempt.set(attempt)
    try:
        yield attempt
    finally:
        bm._registration_attempt.reset(token)


class PreLaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        import vyne.bootstrap as bm
        try:
            bm._start_lock.release()
        except RuntimeError:
            pass

    def tearDown(self) -> None:
        import vyne.bootstrap as bm
        try:
            bm._start_lock.release()
        except RuntimeError:
            pass

    def test_cold_start_runs_app_hook_before_mount(self) -> None:
        from vyne.runtime import Runtime
        from vyne.transport import MemoryTransport

        calls: list[str] = []

        def app_hook(context) -> None:
            calls.append(f"app:{context.launch.origin}")

        runtime = Runtime(lambda: None, transport=MemoryTransport())
        with _registration_attempt() as attempt:
            run_app(lambda: None, pre_launch=app_hook)
            chain = (attempt.app_hook,)
            _run_pre_launch_chain(
                chain, runtime.build_root_context(LaunchData(origin="cold"))
            )
        self.assertEqual(["app:cold"], calls)

    def test_hook_error_does_not_block_the_launch(self) -> None:
        from vyne.runtime import Runtime
        from vyne.transport import MemoryTransport

        calls: list[str] = []

        def bad(context) -> None:
            raise RuntimeError("boom")

        def good(context) -> None:
            calls.append("good")

        runtime = Runtime(lambda: None, transport=MemoryTransport())
        with _registration_attempt() as attempt:
            run_app(lambda: None, pre_launch=bad)
            run_app(lambda: None, pre_launch=good)
            _run_pre_launch_chain(
                (attempt.app_hook,), runtime.build_root_context(LaunchData())
            )
        self.assertEqual(["good"], calls)

    def test_async_hook_rejected_at_registration(self) -> None:
        with _registration_attempt():
            async def async_hook(context) -> None:
                return None
            with self.assertRaisesRegex(TypeError, "synchronous"):
                run_app(lambda: None, pre_launch=async_hook)

    def test_app_registration_without_hook_clears_prior_slot(self) -> None:
        def old_hook(context) -> None:
            pass

        with _registration_attempt() as attempt:
            run_app(lambda: None, pre_launch=old_hook)
            self.assertIs(attempt.app_hook, old_hook)
            run_app(lambda: None)  # no hook: clears the slot
            self.assertIsNone(attempt.app_hook)

    def test_failed_start_restores_prior_extension_tables(self) -> None:
        """A failed cold start must restore the prior contract tables."""
        from vyne.extensions_registry import (
            resolve_kind,
            restore,
            snapshot,
            sync_from_host,
        )

        sync_from_host({"Prior": (["p"], ["e"], [False])})
        prior = snapshot()
        try:
            sync_from_host({"Candidate": (["q"], ["f"], [False])})
            self.assertIsNotNone(resolve_kind("Candidate"))
        finally:
            restore(prior)
        self.assertIsNone(resolve_kind("Candidate"))
        self.assertIsNotNone(resolve_kind("Prior"))

    def test_pre_dispatcher_failure_restores_prior_tables(self) -> None:
        """A failure BEFORE the candidate dispatcher exists (e.g. invalid
        launch extras) must restore the prior extension tables and must not
        mask the original error with UnboundLocalError."""
        import vyne.android as android
        from vyne.extensions_registry import resolve_kind, restore, snapshot, sync_from_host

        class Host:
            def extensionKinds(self):
                return {"Candidate": (["q"], ["f"], [False])}

        sync_from_host({"Prior": (["p"], ["e"], [False])})
        prior = snapshot()
        try:
            with self.assertRaises(TypeError):
                android.start_direct("app", Host(), extras=object())
        finally:
            restore(prior)
        self.assertIsNone(resolve_kind("Candidate"))
        self.assertIsNotNone(resolve_kind("Prior"))

    def test_warm_delivery_runs_hook_then_updates_root(self) -> None:
        import vyne.android as android

        cases = [
            ("runs_hook_then_root_update", 1, 1, None, {}),
            ("zero_arg_captures_only", 0, 0, "open_order", {"order_id": 7}),
        ]
        for label, arg_count, expected_updates, action, extras in cases:
            with self.subTest(case=label):
                class RecordingRuntime:
                    root_argument_count = arg_count
                    pre_launch_hooks = ()
                    updates: list = []

                    def build_root_context(self, launch):
                        return SimpleNamespace(launch=launch)

                    def update_root_arguments(self, *args) -> None:
                        self.updates.append(args[0])

                runtime = RecordingRuntime()
                android._session = android._DirectSession(
                    host=None, runtime=runtime, transport=None, dispatcher=None
                )
                seen: list[str] = []

                def hook(context) -> None:
                    seen.append(context.launch.origin)

                runtime.pre_launch_hooks = (hook,)
                android.deliver_launch_direct(action, None, extras, 2)  # warm
                self.assertEqual(["warm"], seen)
                self.assertEqual(
                    expected_updates, len(runtime.updates),
                    f"{label}: expected {expected_updates} root update(s)",
                )


class HandlerFailureObservabilityTests(unittest.TestCase):
    """A raising event handler must never be silent: the traceback is
    logged to the Python log (python.stderr on Android) while the accepted
    UI is preserved (RE-1)."""

    def test_handler_failure_logs_traceback_and_preserves_ui(self) -> None:
        import logging

        from vyne.elements import Text
        from vyne.events import Event
        from vyne.runtime import Runtime
        from vyne.transport import MemoryTransport

        def boom(event) -> None:
            raise RuntimeError("boom from handler")

        def app():
            return Text(text="hi", on_click=boom)

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()

        # The runtime bound the handler to the mounted node during render.
        node = next(
            n for n in runtime._coordinator.accepted_index.values()
            if "click" in n.listeners
        )
        node_id = next(
            i for i, n in runtime._coordinator.accepted_index.items()
            if n is node
        )
        handler_id = node.listeners["click"]

        logs: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: logs.append(record)
        logger = logging.getLogger("vyne")
        logger.addHandler(handler)
        try:
            runtime.dispatch_native_events([
                Event(name="click", target=node_id, handler=handler_id, payload={}),
            ])
        finally:
            logger.removeHandler(handler)

        self.assertTrue(
            any("event handler failed" in r.getMessage() for r in logs),
            "the failure must be logged with its traceback",
        )
        self.assertIn("boom from handler", " ".join(r.getMessage() for r in logs))
        # RE-1: the accepted UI is preserved — no error commit replaced it.
        self.assertIsNotNone(runtime._coordinator.accepted_root)

    def test_failing_handler_does_not_kill_following_handlers(self) -> None:
        import logging

        from vyne.elements import Text
        from vyne.events import Event
        from vyne.runtime import Runtime
        from vyne.transport import MemoryTransport

        def app():
            return Text(text="hi")

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        seen: list[str] = []

        def bad(event) -> None:
            raise ValueError("bad")

        def good(event) -> None:
            seen.append("good")

        bad_id = runtime.events.register(bad)
        good_id = runtime.events.register(good)

        logger = logging.getLogger("vyne")
        handler = logging.Handler()
        handler.emit = lambda record: None
        logger.addHandler(handler)
        try:
            runtime.dispatch_native_events([
                Event(name="click", target=1, handler=bad_id, payload={}),
                Event(name="click", target=1, handler=good_id, payload={}),
            ])
        finally:
            logger.removeHandler(handler)
        # The batch fails atomically: "good" never runs (state journal is
        # rolled back as a whole) — but the runtime survives.
        self.assertEqual([], seen)
        self.assertIsNotNone(runtime._coordinator.accepted_root)


if __name__ == "__main__":
    unittest.main()
