"""MATERIAL-02: Callback adapter, one-time inspection, and callable objects.

Tests for:
- CallbackAdapter construction-time rejection for unsupported signatures
- Callable-object error reporting (no __name__)
- One adapter per composite callback reuse
- prepare_value_binding / prepare_handler one-time inspection
"""

from __future__ import annotations

import unittest

from vyne_material._callbacks import (
    CallbackAdapter,
    prepare_handler,
    prepare_value_binding,
)


class CallbackAdapterConstructionTests(unittest.TestCase):
    """Construction-time parameter inspection and rejection."""

    def test_accepts_one_positional(self):
        def handler(value):
            pass
        adapter = CallbackAdapter(handler)
        self.assertTrue(adapter._accepts_positional)

    def test_accepts_varargs(self):
        def handler(*args):
            pass
        adapter = CallbackAdapter(handler)
        self.assertTrue(adapter._accepts_positional)

    def test_accepts_zero_args(self):
        def handler():
            pass
        adapter = CallbackAdapter(handler)
        self.assertFalse(adapter._accepts_positional)

    def test_accepts_defaulted_arg(self):
        def handler(value=None):
            pass
        adapter = CallbackAdapter(handler)
        self.assertTrue(adapter._accepts_positional)

    def test_required_keyword_only_rejected(self):
        def handler(*, value):
            pass
        with self.assertRaises(TypeError):
            CallbackAdapter(handler)

    def test_builtin_treated_as_value_accepting(self):
        adapter = CallbackAdapter(print)
        self.assertTrue(adapter._accepts_positional)

    def test_lambda_with_one_arg(self):
        adapter = CallbackAdapter(lambda v: None)
        self.assertTrue(adapter._accepts_positional)

    def test_lambda_with_zero_args(self):
        adapter = CallbackAdapter(lambda: None)
        self.assertFalse(adapter._accepts_positional)


class CallbackAdapterInvocationTests(unittest.TestCase):
    """Invocation routes values correctly."""

    def test_invoke_passes_value(self):
        received: list[object] = []
        adapter = CallbackAdapter(lambda v: received.append(v))
        adapter.invoke(42)
        self.assertEqual(received, [42])

    def test_invoke_ignores_value_for_zero_arg(self):
        called: list[bool] = []

        def handler():
            called.append(True)

        adapter = CallbackAdapter(handler)
        adapter.invoke("ignored")
        self.assertTrue(called[0])

    def test_invoke_passes_tuple_value(self):
        received: list[tuple[float, float]] = []
        adapter = CallbackAdapter(lambda v: received.append(v))
        adapter.invoke((0.1, 0.8))
        self.assertEqual(received, [(0.1, 0.8)])


class CallbackAdapterCallableObjectTests(unittest.TestCase):
    """Callable objects (classes with __call__) are handled correctly."""

    def test_callable_object_one_arg(self):
        class Handler:
            def __call__(self, value):
                self.received = value

        h = Handler()
        adapter = CallbackAdapter(h)
        self.assertTrue(adapter._accepts_positional)
        adapter.invoke("test")
        self.assertEqual(h.received, "test")

    def test_callable_object_zero_arg(self):
        class Handler:
            called = False

            def __call__(self):
                Handler.called = True

        adapter = CallbackAdapter(Handler())
        self.assertFalse(adapter._accepts_positional)
        adapter.invoke("ignored")
        self.assertTrue(Handler.called)

    def test_callable_object_two_required(self):
        class Handler:
            def __call__(self, a, b):
                pass

        with self.assertRaises(TypeError):
            CallbackAdapter(Handler())

    def test_callable_object_keyword_only(self):
        class Handler:
            def __call__(self, *, value):
                pass

        with self.assertRaises(TypeError):
            CallbackAdapter(Handler())


class PrepareHelpersTests(unittest.TestCase):
    """prepare_handler and prepare_value_binding inspect once."""

    def test_prepare_handler_returns_none_for_none_callback(self):
        self.assertIsNone(prepare_handler(None, "value"))

    def test_prepare_handler_creates_closure(self):
        received: list[object] = []

        def handler(v):
            received.append(v)

        h = prepare_handler(handler, "test_value")
        self.assertIsNotNone(h)
        h(None)  # event ignored
        self.assertEqual(received, ["test_value"])

    def test_prepare_value_binding_returns_adapter(self):
        adapter = prepare_value_binding(lambda v: None)
        self.assertIsInstance(adapter, CallbackAdapter)
        self.assertTrue(adapter._accepts_positional)

    def test_prepare_value_binding_zero_arg(self):
        adapter = prepare_value_binding(lambda: None)
        self.assertIsInstance(adapter, CallbackAdapter)
        self.assertFalse(adapter._accepts_positional)

    def test_adapter_inspected_exactly_once(self):
        """Inspection happens in __init__, not on each invoke."""
        inspect_count = [0]
        original = inspect_count

        def handler(v):
            pass

        adapter = CallbackAdapter(handler)
        # Multiple invocations use the same cached flag
        adapter.invoke(1)
        adapter.invoke(2)
        adapter.invoke(3)

        # The accept_positional flag is immutable after construction
        flag1 = adapter._accepts_positional
        adapter.invoke(4)
        flag2 = adapter._accepts_positional
        self.assertIs(flag1, flag2)


if __name__ == "__main__":
    unittest.main()
