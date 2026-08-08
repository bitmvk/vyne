"""Tests for element occurrence identity and Ref lifecycle (MODEL-02 / MO-2).

Covers:
- Duplicate Element occurrences produce distinct mounts
- Cross-runtime Element reuse produces independent RenderNodes
- Ref cannot be shared across multiple elements
- Ref attach/unattach lifecycle is coherent
- Per-mount Ref ownership
"""

from __future__ import annotations

import unittest

from vyne.values import FrozenMap
from vyne.lowering import lower_element, CanonicalElement
from vyne.elements import (
    Element, Box, Text, Layout,
)
from vyne.refs import Ref, ViewHandle
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport
from vyne.component import component


class DuplicateElementOccurrenceTests(unittest.TestCase):
    """MO-2: Duplicate Element occurrences and cross-runtime reuse produce
    distinct mounts."""

    def test_same_element_used_twice_creates_two_nodes(self):
        """Using the same Element object twice creates distinct RenderNodes."""
        child = Text(text="repeated")
        root = Box(child, child)

        rt = Runtime(lambda: root, transport=MemoryTransport())
        rt._mounted = True
        rt._render_once()

        # Should have 3 nodes: root Box + 2 Text children
        self.assertGreaterEqual(len(rt._coordinator.accepted_index), 3,
            "Duplicate Element should create distinct nodes")

        # The two Text nodes should have different IDs
        text_nodes = [n for n in rt._coordinator.accepted_index.values() if n.kind == "Text"]
        self.assertEqual(len(text_nodes), 2,
            f"Expected 2 Text nodes, got {len(text_nodes)}")
        self.assertNotEqual(text_nodes[0].id, text_nodes[1].id,
            "Duplicate Element children must have distinct node IDs")

    def test_same_element_in_list_creates_distinct_nodes(self):
        """Using the same Element multiple times in a list creates distinct nodes."""
        shared = Text(text="item")
        root = Box(*(shared for _ in range(5)))

        rt = Runtime(lambda: root, transport=MemoryTransport())
        rt._mounted = True
        rt._render_once()

        text_nodes = [n for n in rt._coordinator.accepted_index.values() if n.kind == "Text"]
        self.assertEqual(len(text_nodes), 5,
            f"Expected 5 Text nodes, got {len(text_nodes)}")
        # All IDs must be distinct
        ids = {n.id for n in text_nodes}
        self.assertEqual(len(ids), 5,
            "All duplicate Element occurrences must have distinct IDs")

    def test_same_element_used_across_components(self):
        """The same Element reused in different component call sites creates
        distinct nodes."""
        shared_child = Text(text="shared")

        @component
        def CompA():
            return Box(shared_child)

        @component
        def CompB():
            return Box(shared_child)

        root = Box(CompA(), CompB())

        rt = Runtime(lambda: root, transport=MemoryTransport())
        rt._mounted = True
        rt._render_once()

        text_nodes = [n for n in rt._coordinator.accepted_index.values() if n.kind == "Text"]
        self.assertEqual(len(text_nodes), 2,
            f"Cross-component Element reuse must create distinct nodes")

    def test_distinct_but_equal_elements_are_different_occurrences(self):
        """Two distinct Element objects with identical content are different occurrences."""
        e1 = Text(text="hello")
        e2 = Text(text="hello")
        root = Box(e1, e2)

        rt = Runtime(lambda: root, transport=MemoryTransport())
        rt._mounted = True
        rt._render_once()

        text_nodes = [n for n in rt._coordinator.accepted_index.values() if n.kind == "Text"]
        self.assertEqual(len(text_nodes), 2)
        self.assertNotEqual(text_nodes[0].id, text_nodes[1].id)


class RefOccurrenceTests(unittest.TestCase):
    """Ref lifecycle and ownership tests."""

    def test_ref_attached_to_one_element(self):
        """A Ref attached to a single element works correctly."""
        ref = Ref()
        root = Box(ref=ref)

        rt = Runtime(lambda: root, transport=MemoryTransport())
        rt._mounted = True
        rt._render_once()

        self.assertIsNotNone(ref.current)
        self.assertTrue(ref.current.valid)

    def test_same_ref_on_two_elements_rejects(self):
        """The same Ref object must not be shared across elements.
        This is a user error that should be detected before publication."""
        ref = Ref()
        child1 = Text(text="a", ref=ref)
        child2 = Text(text="b", ref=ref)
        root = Box(child1, child2)

        transport = MemoryTransport()
        rt = Runtime(lambda: root, transport=transport)
        rt.mount()

        self.assertIsNone(ref.current)
        self.assertIsNone(rt._coordinator.accepted_root)
        self.assertIn("multiple mounted occurrences", str(rt.latest_commit))

    def test_ref_update_during_diff(self):
        """Changing the ref prop during update should transition correctly."""
        ref1 = Ref()
        ref2 = Ref()

        # Simple test: mount with ref1, then re-render with ref2.
        called_flag = {"count": 0}

        @component
        def MyApp():
            count = called_flag["count"]
            if count == 0:
                return Box(Text(text="initial"), ref=ref1)
            return Box(Text(text="updated"), ref=ref2)

        rt = Runtime(MyApp, transport=MemoryTransport())

        # Custom transport to track commits
        class TestTransport(MemoryTransport):
            def send(self, commit, revision=0):
                return revision

        rt.transport = TestTransport()
        rt.mount()
        initial_revision = rt.latest_commit["revision"]
        self.assertIsNone(ref1.current)
        rt.acknowledge_native_apply(initial_revision)

        self.assertIsNotNone(ref1.current)
        self.assertTrue(ref1.current.valid)

        # Trigger update by changing the flag and requesting render
        called_flag["count"] = 1
        rt.request_render()
        update_revision = rt.latest_commit["revision"]
        # Pre-ack publication leaves the accepted ref untouched.
        self.assertIsNotNone(ref1.current)
        self.assertIsNone(ref2.current)
        rt.acknowledge_native_apply(update_revision)

        # ref1 should now be invalidated (old node removed)
        self.assertIsNone(ref1.current,
            f"ref1 should be invalidated after update, got {ref1.current}")
        # ref2 should now be valid (new node mounted)
        self.assertIsNotNone(ref2.current,
            "ref2 should be attached after update")
        self.assertTrue(ref2.current.valid)

    def test_two_live_refs_can_swap_occurrences_atomically(self):
        ref1 = Ref()
        ref2 = Ref()
        swapped = {"value": False}

        def app():
            first, second = (
                (ref2, ref1) if swapped["value"] else (ref1, ref2)
            )
            return Box(
                Text(text="a", ref=first),
                Text(text="b", ref=second),
            )

        runtime = Runtime(app, transport=MemoryTransport())
        runtime.mount()
        first_node = ref1.current.node_id
        second_node = ref2.current.node_id

        swapped["value"] = True
        runtime.request_render()

        self.assertEqual(ref1.current.node_id, second_node)
        self.assertEqual(ref2.current.node_id, first_node)

    def test_ref_invalidation_on_node_removal(self):
        """When a node with a Ref is removed, the Ref must invalidate."""
        ref = Ref()
        state = {"show": True}

        @component
        def MyApp():
            if state["show"]:
                return Box(Text(text="removable", ref=ref))
            return Box(Text(text="empty"))

        rt = Runtime(MyApp, transport=MemoryTransport())
        rt.mount()

        self.assertIsNotNone(ref.current)
        self.assertTrue(ref.current.valid)

        # Now remove the ref'd node by changing state
        state["show"] = False
        rt.request_render()

        self.assertIsNone(ref.current, "Ref must invalidate on node removal")

    def test_ref_viewhandle_independent_per_occurrence(self):
        """Each Ref occurrence gets an independent ViewHandle."""
        ref1 = Ref()
        ref2 = Ref()
        root = Box(
            Text(text="a", ref=ref1),
            Text(text="b", ref=ref2),
        )

        rt = Runtime(lambda: root, transport=MemoryTransport())
        rt._mounted = True
        rt._render_once()

        self.assertIsNotNone(ref1.current)
        self.assertIsNotNone(ref2.current)
        self.assertNotEqual(ref1.current.node_id, ref2.current.node_id)
        self.assertNotEqual(id(ref1.current), id(ref2.current))

    def test_ref_reuse_after_dispose(self):
        """After a Runtime is disposed, all refs must be invalidated."""
        ref = Ref()
        root = Box(ref=ref)

        rt = Runtime(lambda: root, transport=MemoryTransport())
        rt.mount()

        self.assertIsNotNone(ref.current)
        rt.dispose()

        self.assertIsNone(ref.current)


class CanonicalElementOccurrenceTests(unittest.TestCase):
    """Lowered elements produce independent occurrences."""

    def test_lower_twice_creates_distinct_canonical_elements(self):
        """Lowering the same Element twice produces distinct CanonicalElements."""
        elem = Text(text="hello")
        c1 = lower_element(elem)
        c2 = lower_element(elem)
        # They should be equal (same content)
        self.assertEqual(c1, c2)
        # But they are different objects (each occurrence is independent)
        # This is important for diffing — each use of the same Element
        # in the tree is a separate occurrence.
        self.assertIsNot(c1, c2)

    def test_canonical_children_are_frozen(self):
        """CanonicalElement children must be immutable."""
        elem = Box(Text(text="a"), Text(text="b"))
        canon = lower_element(elem)
        self.assertIsInstance(canon.children, tuple)
        with self.assertRaises(Exception):
            canon.children[0] = None  # tuple mutation fails


if __name__ == "__main__":
    unittest.main()
