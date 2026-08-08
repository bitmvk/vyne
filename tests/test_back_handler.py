from __future__ import annotations

import unittest

from vyne import AppContext, BackHandler, LaunchData, Text
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


class BackHandlerTests(unittest.TestCase):
    def _runtime(self, app) -> Runtime:
        runtime = Runtime(app, transport=MemoryTransport())
        runtime.set_context_root(LaunchData(sequence=1))
        runtime.mount()
        return runtime

    def test_no_handlers_does_not_consume(self) -> None:
        runtime = self._runtime(lambda context: Text(text="x"))
        self.assertFalse(runtime.handle_back_press())

    def test_true_handler_consumes(self) -> None:
        ran: list[str] = []

        def app(context: AppContext):
            context.back_handler.addEventListener(lambda: ran.append("b") or True)
            return Text(text="x")

        runtime = self._runtime(app)
        self.assertTrue(runtime.handle_back_press())
        self.assertEqual(ran, ["b"])

    def test_lifo_order_first_true_wins(self) -> None:
        ran: list[str] = []

        def app(context: AppContext):
            context.back_handler.addEventListener(lambda: ran.append("a") or False)
            context.back_handler.addEventListener(lambda: ran.append("b") or True)
            context.back_handler.addEventListener(lambda: ran.append("c") or False)
            return Text(text="x")

        runtime = self._runtime(app)
        self.assertTrue(runtime.handle_back_press())
        self.assertEqual(ran, ["c", "b"])

    def test_all_false_does_not_consume(self) -> None:
        ran: list[str] = []

        def app(context: AppContext):
            context.back_handler.addEventListener(lambda: ran.append("a") or False)
            context.back_handler.addEventListener(lambda: ran.append("b") or False)
            return Text(text="x")

        runtime = self._runtime(app)
        self.assertFalse(runtime.handle_back_press())
        self.assertEqual(ran, ["b", "a"])

    def test_dispose_removes_handler(self) -> None:
        ran: list[str] = []
        holder: dict[str, object] = {}

        def app(context: AppContext):
            holder["dispose"] = context.back_handler.addEventListener(
                lambda: ran.append("b") or True
            )
            return Text(text="x")

        runtime = self._runtime(app)
        holder["dispose"]()  # type: ignore[operator]
        self.assertFalse(runtime.handle_back_press())
        self.assertEqual(ran, [])

    def test_raising_handler_is_false_and_others_run(self) -> None:
        ran: list[str] = []

        def app(context: AppContext):
            def bad():
                raise RuntimeError("boom")

            context.back_handler.addEventListener(bad)
            context.back_handler.addEventListener(lambda: ran.append("b") or True)
            return Text(text="x")

        runtime = self._runtime(app)
        self.assertTrue(runtime.handle_back_press())
        self.assertEqual(ran, ["b"])

    def test_re_registration_does_not_duplicate(self) -> None:
        ran: list[str] = []
        handler = lambda: ran.append("b") or True

        def app(context: AppContext):
            context.back_handler.addEventListener(handler)
            context.back_handler.addEventListener(handler)
            return Text(text="x")

        runtime = self._runtime(app)
        self.assertTrue(runtime.handle_back_press())
        self.assertEqual(ran, ["b"])

    def test_warm_launch_re_render_does_not_duplicate(self) -> None:
        ran: list[str] = []
        holder: dict[str, object] = {}

        def app(context: AppContext):
            holder["handler"] = lambda: ran.append("b") or True
            context.back_handler.addEventListener(holder["handler"])  # type: ignore[arg-type]
            return Text(text="x")

        runtime = self._runtime(app)
        runtime.update_root_arguments(
            runtime.build_root_context(LaunchData(sequence=2))
        )
        self.assertTrue(runtime.handle_back_press())
        self.assertEqual(ran, ["b"])

    def test_handler_may_take_no_arguments_only(self) -> None:
        def app(context: AppContext):
            with self.assertRaises(TypeError):
                context.back_handler.addEventListener(42)
            return Text(text="x")

        self._runtime(app)

    def test_wrappers_share_one_runtime_registry(self) -> None:
        observed: list[BackHandler] = []

        def app(context: AppContext):
            observed.append(context.back_handler)
            return Text(text="x")

        runtime = self._runtime(app)
        runtime.update_root_arguments(
            runtime.build_root_context(LaunchData(sequence=2))
        )
        self.assertIs(observed[0]._runtime, observed[1]._runtime)
        self.assertIs(observed[1]._runtime, runtime)


if __name__ == "__main__":
    unittest.main()
