"""Element constructors exposed to user applications.

Each constructor (Box, Text, Row, etc.) returns a frozen ``Element`` dataclass
that captures the widget kind, normalized props, and children.  Elements are
plain immutable data — no layout, no rendering, no side effects.

The lowering pipeline in ``vyne.lowering`` converts these public Elements into
``CanonicalElement`` instances with fully resolved, flat, validated props before
they reach the runtime diff engine.

Key design decisions:
- Event handlers (on_click, etc.) are stored in props and split out later
  by the Runtime via ``_split_props``.  They are not sent as data props.
- ``normalize_children`` flattens nested lists/tuples and converts scalars
  (str/int/float/bool) into Text elements, so users can write natural
  child expressions like ``Box("Hello", [Text(text="world")])``.
- Path data strings and Canvas draw lists are compiled at Element creation
  time (not render time) to fail-fast on malformed input.
- Element has no runtime identity fields (no ``_view_id``, no ``_validated``).
  Runtime identity lives exclusively on ``RenderNode``.  Each occurrence gets
  an independent RenderNode, including duplicate/cross-runtime reuse of the
  same Element object.

Precise per-constructor typing lives in the generated ``elements.pyi``
(regenerated from ``vyne.spec.schema_v2`` by
``scripts/generate_schema_stubs.py``).  This module keeps runtime
annotations loose so no generated metadata is imported at runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from vyne.protocol import (
    ensure_bridge_value,
)
from vyne.path_data import compile_path_data
from vyne.animations import encode_animated_values
from vyne.values import FrozenMap
from vyne.extensions_registry import event_name_for_prop as _merged_event_name




@dataclass(frozen=True)
class Element:
    """Platform-neutral UI node with no runtime identity.

    Element is deeply frozen — all reachable values are immutable.
    Runtime identity (node IDs, view handles) lives exclusively on the
    ``RenderNode`` tree managed by the Runtime.  The same Element object
    can be reused across renders and each occurrence gets its own
    independent RenderNode.

    Props are stored as a FrozenMap to enforce recursive immutability
    (MODEL-03).  Mutating props after construction is caught by the
    frozen dataclass wrapper at the top level and by FrozenMap at the
    mapping level.
    """

    kind: str
    props: FrozenMap = field(default_factory=FrozenMap)
    children: tuple["Element", ...] = ()

    def __post_init__(self) -> None:
        """Take one canonical, non-mutating snapshot of all public values."""
        from vyne.values import freeze, validate_canonical_key

        if not isinstance(self.props, Mapping):
            raise TypeError(
                f"Element props must be a mapping, got {type(self.props).__name__}"
            )

        # Validate the caller's key against the canonical key domain before
        # freezing.  Opaque/mutable hashables (custom objects, floats, bools)
        # are rejected at construction rather than silently accepted.
        key_value = self.props.get("key")
        if key_value is not None:
            validate_canonical_key(key_value, path="Element key")

        # Always rebuild, including when the input is already FrozenMap: an
        # externally-created FrozenMap can still contain mutable descendants.
        # Never pop from or otherwise mutate the caller's mapping.
        frozen_props = FrozenMap(
            (name, value if name == "key" else freeze(value))
            for name, value in self.props.items()
        )
        frozen_children = tuple(freeze(child) for child in tuple(self.children))
        if not all(isinstance(child, Element) for child in frozen_children):
            bad = next(child for child in frozen_children if not isinstance(child, Element))
            raise TypeError(
                f"Element children must contain Elements, got {type(bad).__name__}"
            )
        object.__setattr__(self, "props", frozen_props)
        object.__setattr__(self, "children", frozen_children)


def _widget(kind: str, *children: Any, **props: Any) -> Element:
    """Internal constructor shared by all widget helpers.

    Normalizes props, validates direct-bridge values for non-event props,
    normalizes children (flattening lists, converting scalars to Text),
    and returns a frozen Element with recursively immutable props.
    """
    normalized_props = props
    # Validate bridge compatibility once at element creation, not per render.
    # This fails fast so malformed input never reaches the diff loop.
    for name, value in normalized_props.items():
        if (
            value is not None
            and event_name_for_prop(name) is None
            and name != "key"
            and name not in ("decoration", "ref")
        ):
            ensure_bridge_value(value, prop_name=name)
            normalized_props[name] = encode_animated_values(value)
    # Element performs the single canonical deep copy.  Preserve ``key`` in
    # its original form so Element can reject mutable keys before freezing.
    return Element(kind, normalized_props, normalize_children(children))


def Box(*children: Any, **props: Any) -> Element:
    return _widget("Box", *children, **props)


def Layout(*children: Any, **props: Any) -> Element:
    return _widget("Layout", *children, **props)


def Row(*children: Any, **props: Any) -> Element:
    return _widget("Layout", *children, orientation="horizontal", **props)


def Column(*children: Any, **props: Any) -> Element:
    return _widget("Layout", *children, orientation="vertical", **props)


def Scroll(*children: Any, **props: Any) -> Element:
    """A vertical scrollable container.

    The canonical Scroll contract has one direct content child, so multiple
    children are auto-wrapped in a Column on every host.
    """
    normalized = normalize_children(children)
    if len(normalized) > 1:
        normalized = (Column(*normalized),)
    props.setdefault("overflow", "hidden")
    return _widget("Scroll", *normalized, **props)


def _horizontal_scroll(
    *children: Any,
    **props: Any,
) -> Element:
    """Private horizontal scroll primitive used by internal controllers."""
    normalized = normalize_children(children)
    if len(normalized) > 1:
        normalized = (Row(*normalized),)
    props.setdefault("overflow", "hidden")
    return _widget("HorizontalScroll", *normalized, **props)


def Text(**props: Any) -> Element:
    return _widget("Text", **props)


def TextInput(**props: Any) -> Element:
    return _widget("TextInput", **props)


def Image(**props: Any) -> Element:
    return _widget("Image", **props)


def Path(**props: Any) -> Element:
    """An SVG-path-backed vector shape.

    The ``d`` attribute is compiled at creation time into a list of JSON-safe
    drawing commands, keeping malformed path strings out of the Android UI
    thread.
    """
    normalized = dict(props)
    d = normalized.pop("d", None)
    if d is not None:
        normalized["commands"] = compile_path_data(d)
    return _widget("Path", **normalized)


def Canvas(**props: Any) -> Element:
    """A declarative 2D drawing surface.

    The ``draw`` list describes drawing operations (round_rect, path, etc.)
    as JSON dicts.  Any embedded path data (``d`` in a path operation) is
    compiled just like a standalone Path element.
    """
    normalized = dict(props)
    draw = normalized.get("draw")
    if draw is not None:
        normalized["draw"] = _compile_canvas_draw(draw)
    return _widget("Canvas", **normalized)


def normalize_child(child: Any) -> Element:
    if isinstance(child, Element):
        return child
    if isinstance(child, str | int | float | bool):
        return Text(text=str(child))
    raise TypeError(f"Cannot render child of type {type(child).__name__}")


def normalize_children(children: tuple[Any, ...]) -> tuple[Element, ...]:
    """Flatten and normalize a varargs children tuple.

    - ``None`` children are silently dropped.
    - Nested lists/tuples are recursively flattened.
    - Scalars (str, int, float, bool) are converted to Text elements.
    """
    normalized: list[Element] = []
    for child in children:
        if child is None:
            continue
        if isinstance(child, list | tuple):
            normalized.extend(normalize_children(tuple(child)))
        else:
            normalized.append(normalize_child(child))
    return tuple(normalized)


def event_name_for_prop(prop_name: str) -> str | None:
    """Map an event-handler prop (``on_click``) to its event name.

    Core events come from the static schema map; extension events are
    derived from the host-synced event names via the ``on_`` prefix.
    """
    return _merged_event_name(prop_name)


def _compile_canvas_draw(draw: Any) -> list[dict[str, Any]]:
    if not isinstance(draw, list):
        raise TypeError("Canvas draw must be a list of drawing operations")

    compiled: list[dict[str, Any]] = []
    for operation in draw:
        if not isinstance(operation, dict):
            raise TypeError("Canvas drawing operations must be dictionaries")
        item = dict(operation)
        if item.get("kind") == "path" and "d" in item:
            d = item.pop("d")
            item["commands"] = compile_path_data(d)
        compiled.append(item)
    return compiled
