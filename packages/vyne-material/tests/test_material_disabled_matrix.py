"""Disabled-first precedence matrix for Material components (MAT-11).

Every interactive component must:
- Clear click/long-click handlers when disabled
- Use disabled color palette (on_surface at 0.38 opacity)
- Have no active ripple (transparent)
- Preserve the selection indicator in disabled palette

Covers: Navigation, Drawer, Chip, Segmented, Tab, FAB menu leaves.
"""

from __future__ import annotations

import unittest

from vyne_material import (
    Button,
    Checkbox,
    Chip,
    FloatingActionButton,
    FloatingActionButtonMenu,
    FabMenuItem,
    IconButton,
    NavigationBar,
    NavigationDrawer,
    NavigationItem,
    NavigationRail,
    RadioButton,
    SegmentedButton,
    SegmentedButtonGroup,
    SegmentedItem,
    Slider,
    Switch,
    TabItem,
    Tabs,
    DEFAULT_THEME,
)
from vyne_material._foundation import alpha


class DisabledMatrixTests(unittest.TestCase):
    """Every interactive component respects disabled-first precedence."""

    def _click_clear_cases(self):
        return [
            ("button", Button("Click", enabled=False), "on_click"),
            ("icon_button", IconButton("+", enabled=False), "on_click"),
            ("fab", FloatingActionButton("+", enabled=False), "on_click"),
            ("checkbox", Checkbox(False, enabled=False), "on_click"),
            ("switch", Switch(False, enabled=False), "on_click"),
            ("radio", RadioButton(False, enabled=False), "on_click"),
            ("chip", Chip("Filter", enabled=False), "on_click"),
            ("segmented", SegmentedButton("Opt", selected=False, enabled=False), "on_click"),
            ("slider", Slider(0.5, enabled=False), "on_pointer_down"),
        ]

    def test_disabled_components_clear_handlers(self):
        """Disabled components expose no click/pointer handlers."""
        for name, component, prop in self._click_clear_cases():
            with self.subTest(component=name, prop=prop):
                self.assertIsNone(component.props.get(prop))

    def test_disabled_slider_clears_all_pointers(self):
        sl = Slider(0.5, enabled=False)
        self.assertIsNone(sl.props.get("on_pointer_down"))
        self.assertIsNone(sl.props.get("on_pointer_move"))
        self.assertIsNone(sl.props.get("on_pointer_up"))

    def test_disabled_button_uses_disabled_colors(self):
        btn = Button("Click", enabled=False)
        # Disabled foreground is on_surface at 0.38, container at 0.12.
        label = next(c for c in btn.children if c.kind == "Text")
        expected_fg = alpha(DEFAULT_THEME.colors.on_surface, 0.38)
        self.assertEqual(label.props["text_color"], expected_fg)
        self.assertEqual(
            btn.props["background_color"],
            alpha(DEFAULT_THEME.colors.on_surface, 0.12),
        )


class NavigationDisabledTests(unittest.TestCase):
    """Navigation components respect disabled-first precedence."""

    def test_nav_bar_disabled_item_clears_click(self):
        items = [
            NavigationItem("Home", "H", enabled=False),
            NavigationItem("Saved", "S"),
        ]
        bar = NavigationBar(items)
        # NavigationBar is a Row; each item is a navigation_destination.
        # A disabled item should have no on_click.
        disabled = [
            child for child in bar.children
            if child.kind in ("Layout", "Box")
            and child.props.get("enabled") is False
        ]
        self.assertTrue(
            disabled,
            "NavigationBar must contain a disabled destination",
        )
        for child in disabled:
            self.assertIsNone(child.props.get("on_click"))

    def test_nav_rail_disabled_item_clears_click(self):
        items = [
            NavigationItem("Home", "H", enabled=False),
            NavigationItem("Saved", "S"),
        ]
        rail = NavigationRail(items)
        # NavigationRail is a Column
        disabled = [
            child for child in rail.children
            if child.kind in ("Layout", "Box")
            and child.props.get("enabled") is False
        ]
        self.assertTrue(
            disabled,
            "NavigationRail must contain a disabled destination",
        )
        for child in disabled:
            self.assertIsNone(child.props.get("on_click"))

    def test_nav_drawer_disabled_item_clears_click(self):
        items = [
            NavigationItem("Home", "H", enabled=False),
            NavigationItem("Saved", "S"),
        ]
        drawer = NavigationDrawer(items)
        # NavigationDrawer is a Column; items are wrapped in rows
        disabled = [
            child for child in drawer.children
            if child.kind == "Layout"
            and child.props.get("enabled") is False
        ]
        self.assertTrue(
            disabled,
            "NavigationDrawer must contain a disabled destination",
        )
        for child in disabled:
            self.assertIsNone(child.props.get("on_click"))


class DisabledPreservesSelectionTests(unittest.TestCase):
    """Disabled components still render their selection indicator."""

    def test_disabled_chip_selected_renders(self):
        """Chip with selected=True but enabled=False still renders."""
        chip = Chip("Filter", selected=True, variant="filter", enabled=False)
        # Should have a leading element (selected checkmark slot)
        leading = chip.children[0]
        self.assertIn(leading.kind, ("Box", "Layout"))  # selected slot

    def test_disabled_segmented_selected_renders(self):
        """SegmentedButton with selected=True but enabled=False."""
        sb = SegmentedButton("Opt", selected=True, enabled=False, start=True, end=True)
        # Selected slot renders the leading checkmark indicator.
        leading = sb.children[0]
        self.assertIn(leading.kind, ("Box", "Layout"))
        self.assertIsNone(sb.props.get("on_click"))

    def test_disabled_tab_selected_renders(self):
        """Tab with selected=True but enabled=False."""
        tab = Tabs(
            [TabItem("One", enabled=False), TabItem("Two")],
            selected_index=0,
        )
        # The selected disabled tab still renders its label Text deep in its
        # subtree and carries enabled=False on its root Box.
        def has_label(element, label):
            if element.kind == "Text" and element.props.get("text") == label:
                return True
            return any(has_label(child, label) for child in element.children)

        one_box = tab.children[0]
        self.assertFalse(one_box.props.get("enabled"))
        self.assertTrue(has_label(one_box, "One"))


class FABMenuDisabledTests(unittest.TestCase):
    """FAB menu leaves respect disabled state."""

    def test_fab_menu_disabled_item_clears_click(self):
        items = [
            FabMenuItem("Create", "+", enabled=False),
            FabMenuItem("Edit", "✎"),
        ]
        menu = FloatingActionButtonMenu(items, expanded=True)
        # Label leaf Layouts carry the item's enabled flag: the disabled item
        # renders its label in a disabled leaf, the enabled item in an
        # enabled leaf.
        stack = [menu]
        leaves: list[tuple[str, object]] = []
        while stack:
            candidate = stack.pop()
            if candidate.kind == "Layout" and any(
                gc.kind == "Text" and gc.props.get("text") in ("Create", "Edit")
                for gc in candidate.children
            ):
                label = next(
                    gc.props.get("text")
                    for gc in candidate.children
                    if gc.kind == "Text"
                )
                leaves.append((label, candidate.props.get("enabled")))
            stack.extend(candidate.children)
        self.assertEqual(sorted(leaves), [("Create", False), ("Edit", True)])


class TabsDisabledTests(unittest.TestCase):
    """Tab disabled state is preserved."""

    def test_disabled_tab_has_no_click(self):
        from vyne_material import Tab as SingleTab
        tab = SingleTab("One", selected=False, enabled=False)
        self.assertIsNone(tab.props.get("on_click"))


if __name__ == "__main__":
    unittest.main()
