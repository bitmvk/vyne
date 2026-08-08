from __future__ import annotations

import unittest

from vyne import Column, Text, component, state
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


class _FailingMemoryTransport(MemoryTransport):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next = False

    def send(self, message) -> None:
        if self.fail_next:
            self.fail_next = False
            raise OSError("injected keyed-component send failure")
        super().send(message)


def _click_listener(commit):
    return next(
        operation
        for operation in commit["ops"]
        if operation.get("op") == "listen"
        and operation.get("event") == "click"
    )


class KeyedComponentTests(unittest.TestCase):
    def test_reorder_preserves_component_state_and_native_identity(self) -> None:
        order_cell = None
        item_cells = {}

        @component(key=lambda name: name)
        def Item(name: str):
            value = state(name.upper())
            item_cells[name] = value
            return Text(text=value.value)

        def App():
            nonlocal order_cell
            order_cell = state(("a", "b"))
            return Column(*(Item(name) for name in order_cell.value))

        runtime = Runtime(App, transport=MemoryTransport())
        runtime.mount()

        initial_children = runtime._coordinator.accepted_root.children
        initial_ids = {child.key: child.id for child in initial_children}
        self.assertEqual([child.key for child in initial_children], ["a", "b"])

        item_cells["a"].set("A-owned")
        order_cell.set(("b", "a"))

        children = runtime._coordinator.accepted_root.children
        self.assertEqual([child.key for child in children], ["b", "a"])
        self.assertEqual([child.props["text"] for child in children], ["B", "A-owned"])
        self.assertEqual(
            {child.key: child.id for child in children},
            initial_ids,
        )
        self.assertEqual(
            [scope.key for scope in runtime._root_scope.children],
            ["b", "a"],
        )

    def test_duplicate_component_keys_fail_before_publication(self) -> None:
        @component(key=lambda _name: "duplicate")
        def Item(name: str):
            return Text(text=name)

        runtime = Runtime(
            lambda: Column(Item("first"), Item("second")),
            transport=MemoryTransport(),
        )
        runtime.mount()

        self.assertIsNotNone(runtime._last_error)
        self.assertIn("Duplicate component key", runtime._last_error)
        self.assertIsNone(runtime._coordinator.accepted_root)

    def test_keyed_component_rejects_conflicting_root_key(self) -> None:
        @component(key=lambda name: name)
        def Item(name: str):
            return Text(text=name, key=f"root-{name}")

        runtime = Runtime(lambda: Item("a"), transport=MemoryTransport())
        runtime.mount()

        self.assertIsNotNone(runtime._last_error)
        self.assertIn("returned root key", runtime._last_error)
        self.assertIsNone(runtime._coordinator.accepted_root)

    def test_send_failure_restores_keyed_scope_order_and_state(self) -> None:
        order_cell = None

        @component(key=lambda name: name)
        def Item(name: str):
            return Text(text=name)

        def App():
            nonlocal order_cell
            order_cell = state(("a", "b"))
            return Column(
                *(Item(name) for name in order_cell.value),
                Text(
                    text="reverse",
                    on_click=lambda: order_cell.set(tuple(reversed(order_cell.value))),
                ),
            )

        transport = _FailingMemoryTransport()
        runtime = Runtime(App, transport=transport)
        runtime.mount()
        listener = _click_listener(runtime.latest_commit)
        accepted_root = runtime._coordinator.accepted_root

        transport.fail_next = True
        runtime.dispatch_event(
            {
                "type": "event",
                "seq": 1,
                "target": listener["id"],
                "event": "click",
                "handler": listener["handler"],
                "payload": {},
            }
        )

        self.assertEqual(order_cell.value, ("a", "b"))
        self.assertEqual(
            [scope.key for scope in runtime._root_scope.children],
            ["a", "b"],
        )
        self.assertIs(runtime._coordinator.accepted_root, accepted_root)

    def test_key_callable_must_return_a_canonical_non_none_key(self) -> None:
        @component(key=lambda _name: None)
        def NoneKey(name: str):
            return Text(text=name)

        none_runtime = Runtime(lambda: NoneKey("a"), transport=MemoryTransport())
        none_runtime.mount()
        self.assertIn("must not return None", none_runtime._last_error)

        @component(key=lambda _name: True)
        def BoolKey(name: str):
            return Text(text=name)

        bool_runtime = Runtime(lambda: BoolKey("a"), transport=MemoryTransport())
        bool_runtime.mount()
        self.assertIn("Component key must be", bool_runtime._last_error)


if __name__ == "__main__":
    unittest.main()
