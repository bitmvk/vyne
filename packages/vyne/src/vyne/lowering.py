"""Lowering pipeline: public elements → canonical flat props.

The lowering pipeline converts user-facing Element trees into fully resolved,
immutable canonical representations before they reach the runtime diff engine.

Precedence: kind defaults < Decoration < explicit direct props.

Shorthands (padding= → padding_top/bottom/start/end, corner_radius= → four corners)
and aliases (alpha → opacity) are resolved into independent canonical slots.
Conflicting explicit aliases reject at lowering time.

Decoration supports solid Fill color, Stroke(color, width without dash), CornerRadius radii,
    Shadow.elevation, Ripple.color → flat properties

Unsupported features reject: gradients (linear/radial/sweep), dashed strokes,
non-rectangle shapes, translation-Z, unbounded ripple, and unknown Decoration
fields.

No ``style``, ``decoration``, or other opaque dicts cross the wire.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from vyne.animations import (
    AnimatedNode,
    encode_animated_values,
    is_animated_node_payload,
)
from vyne.motion import CanvasOpIdentity
from vyne.events import event_delivery
from vyne.values import (
    FrozenMap,
    freeze,
    is_finite_number,
    is_valid_dash_array,
    validate_non_negative,
)

from vyne.extensions_registry import (
    is_event_prop,
    props_by_kind,
    resolve_kind,
    resolve_prop,
)
from vyne.spec.schema_v2 import (
    PRIMITIVE_KINDS,
    validate_path_commands,
    validate_canvas_draw_ops,
)




# ---------------------------------------------------------------------------
# Public lowering entry points
# ---------------------------------------------------------------------------

def lower_element(
    element: Any,
    *,
    _identity_cache: dict[int, tuple[Any, "CanonicalElement"]] | None = None,
    _used_identity_keys: set[int] | None = None,
) -> CanonicalElement:
    """Validate and lower a public Element into a canonical immutable form.

    Returns a ``CanonicalElement`` with flat, fully resolved props.
    Raises TypeError/ValueError for invalid values or unsupported features.
    """
    from vyne.elements import Element

    if not isinstance(element, Element):
        raise TypeError(f"Expected Element, got {type(element).__name__}")

    cache_key = id(element)
    if _identity_cache is not None:
        cached = _identity_cache.get(cache_key)
        if cached is not None and cached[0] is element:
            if _used_identity_keys is not None:
                _used_identity_keys.add(cache_key)
            return cached[1]

    kind = element.kind
    kind_spec = resolve_kind(kind)
    if kind_spec is None:
        raise ValueError(
            f"Unknown primitive kind: {kind!r} — is the extension's Kotlin "
            "registered? (extensions declare kinds through their ElementSpec)"
        )

    # 1. One layer per source: defaults < decoration < explicit props.
    raw_props = dict(element.props)
    explicit_values = {
        name: value
        for name, value in raw_props.items()
        if name not in ("key", "ref", "decoration")
    }
    layers: list[dict[str, Any]] = []
    decoration_value = raw_props.get("decoration")
    if decoration_value is not None:
        layers.append(_lower_decoration(decoration_value, kind))
    layers.append(_normalize_layer(explicit_values))

    # 2. Merge by precedence; the merge decides who wins — no producer
    #    consults another layer's keys.
    resolved = _merge_layers(_materialize_defaults(kind), *layers)

    # 3. ref is a runtime-only prop — pass through without validation.
    if "ref" in raw_props:
        resolved["ref"] = raw_props["ref"]

    # 5b. Normalize dash arrays from user-facing strings to canonical tuples
    resolved = _normalize_dash_arrays(resolved)

    # 6. Validate each prop against the schema
    allowed_props = props_by_kind(kind)
    for name, value in list(resolved.items()):
        # Canonicalize raw animated values: extension constructors build
        # Element directly and may bypass _widget's encoding, so the marker
        # normalization lives here — the single validation point.
        if isinstance(value, AnimatedNode):
            value = encode_animated_values(value)
            resolved[name] = value
        # Remove None values early — they were explicit-null defaults or noise.
        if value is None:
            del resolved[name]
            continue
        if is_event_prop(name, kind):
            callback, delivery = event_delivery(value)
            if delivery not in {"all", "latest"}:
                raise ValueError(
                    f"Unsupported event delivery policy: {delivery!r}"
                )
            if callback is not None and not callable(callback):
                raise TypeError(f"Event handler {name!r} must be callable")
            continue
        if name == "ref":
            continue
        if name not in allowed_props:
            raise ValueError(f"Unsupported prop {name!r} for {kind}")
        prop_spec = resolve_prop(name)
        if prop_spec is not None:
            prop_spec.value.validate(value, path=f"props.{name}")
        else:
            # Extension props declare no value specs: enforce the bridge-safe
            # value domain here so malformed values fail at lowering, not at
            # commit time.
            from vyne.protocol import ensure_bridge_value
            ensure_bridge_value(value, prop_name=name)
        if is_animated_node_payload(value) and (
            prop_spec is None or not prop_spec.animatable
        ):
            raise ValueError(
                f"Animated values are not supported for prop {name!r}; "
                "it is supported by Canvas numeric fields and animatable props"
            )

    # 6b. Deep validation for Canvas/Path ops
    if kind == "Path" and "commands" in resolved:
        validate_path_commands(resolved["commands"], path="props.commands")
    if kind == "Canvas" and "draw" in resolved:
        validate_canvas_draw_ops(resolved["draw"], path="props.draw")
        resolved["draw"] = CanvasOpIdentity.stabilize([
            dict(operation) for operation in resolved["draw"]
        ])
        # Validate view_box if present
        if "view_box" in resolved and resolved["view_box"] is not None:
            vb = resolved["view_box"]
            if not isinstance(vb, (list, tuple)) or len(vb) != 4:
                raise ValueError("view_box must be [x, y, width, height] (4 numbers)")
            for i, v in enumerate(vb):
                if not is_finite_number(v):
                    raise ValueError(f"view_box[{i}] must be a finite number, got {v!r}")
            # Width and height must be positive
            if vb[2] <= 0:
                raise ValueError(f"view_box width must be positive, got {vb[2]!r}")
            if vb[3] <= 0:
                raise ValueError(f"view_box height must be positive, got {vb[3]!r}")

    # 7. Enforce child limits
    children_list: list[CanonicalElement] = []
    seen_keys: set[Any] = set()
    for child in element.children:
        child_key = child.props.get("key")
        if child_key is not None:
            if child_key in seen_keys:
                raise ValueError(
                    f"Duplicate key among {kind} children: {child_key!r}"
                )
            seen_keys.add(child_key)
        children_list.append(lower_element(
            child,
            _identity_cache=_identity_cache,
            _used_identity_keys=_used_identity_keys,
        ))
    children = tuple(children_list)
    if kind_spec.max_children is not None and len(children) > kind_spec.max_children:
        raise ValueError(
            f"{kind} allows at most {kind_spec.max_children} children, "
            f"got {len(children)}"
        )
    for child in children:
        if (
            child.kind not in kind_spec.allowed_children
            and kind_spec.allowed_children
            # Core containers list exactly the core kinds they accept.
            # Extension children are always accepted: the native ViewGroup
            # accepts any View child, and extension kinds declare their own
            # child rules (unrestricted by default).
            and child.kind in PRIMITIVE_KINDS
        ):
            raise ValueError(
                f"{kind} cannot contain a {child.kind} child"
            )

    # 8. Build the canonical element with deeply frozen props.
    # Every value is recursively frozen so nested dicts/lists become
    # FrozenMap/tuple, preventing mutation after lowering (MODEL-03).
    frozen_props = FrozenMap((k, freeze(v)) for k, v in sorted(resolved.items()))
    key_value = raw_props.get("key")

    canonical = CanonicalElement(
        kind=kind,
        props=frozen_props,
        children=children,
        key=key_value,
    )
    if _identity_cache is not None:
        _identity_cache[cache_key] = (element, canonical)
        if _used_identity_keys is not None:
            _used_identity_keys.add(cache_key)
    return canonical


# ---------------------------------------------------------------------------
# CanonicalElement — immutable flat element representation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CanonicalElement:
    """An immutable, fully lowered element description.

    Contains no runtime IDs, cache fields, or mutable state.
    Every occurrence gets an independent RenderNode in the runtime.

    This is the single authoritative definition used by lowering,
    reconciliation, and the runtime.

    Equality and hash are structural — two CanonicalElements with the
    same kind, props, children, and key compare equal and hash the same
    (MODEL-03).
    """
    kind: str
    props: FrozenMap[str, Any]
    children: tuple[CanonicalElement, ...] = ()
    key: Any = None
    # Runtime-only refs and callbacks remain in ``props`` for intent binding.
    # Reconciliation reads this precomputed native projection instead of
    # rebuilding a second CanonicalElement tree for every render.
    native_props: FrozenMap[str, Any] = field(
        init=False,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.key is not None:
            from vyne.values import validate_canonical_key
            validate_canonical_key(self.key, path="CanonicalElement key")
        if "ref" not in self.props and not any(
            is_event_prop(name, self.kind) for name in self.props
        ):
            native_props = self.props
        else:
            native_props = FrozenMap(
                (name, value)
                for name, value in self.props.items()
                if name != "ref" and not is_event_prop(name, self.kind)
            )
        object.__setattr__(self, "native_props", native_props)

    def __hash__(self) -> int:
        return hash((self.kind, self.props, self.children, self.key))


# ---------------------------------------------------------------------------
# Default materialization
# ---------------------------------------------------------------------------

def _normalize_layer(props: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize one raw source layer: aliases, then shorthands."""
    return _resolve_shorthands(_resolve_aliases(dict(props)))


def _merge_layers(defaults: dict[str, Any], *layers: dict[str, Any]) -> dict[str, Any]:
    """Merge layers by precedence with ordered ``dict.update`` (later wins).

    Layers are plain dicts; update preserves insertion order and replaces
    earlier keys, so an explicit value always replaces a same-valued default
    and gets validated — dict semantics never treat ``1 == True`` as equal.
    """
    result = dict(defaults)
    for layer in layers:
        result.update(layer)
    return result


def _materialize_defaults(kind: str) -> dict[str, Any]:
    """Return a dict of canonical defaults for a primitive kind.

    Props with ``drop_default=True`` are excluded — their default
    should not be sent to the native side because the native View's
    inherent behavior is already correct (e.g., ``focusable=False``
    must not disable a TextInput's default editing focus).
    """
    defaults: dict[str, Any] = {}
    allowed = props_by_kind(kind)
    for prop_name in allowed:
        spec = resolve_prop(prop_name)
        if spec is not None and spec.default is not None and not spec.drop_default:
            defaults[prop_name] = spec.default
    return defaults


# ---------------------------------------------------------------------------
# Alias and shorthand resolution
# ---------------------------------------------------------------------------

def _resolve_aliases(props: dict[str, Any]) -> dict[str, Any]:
    """Resolve known aliases into canonical slots.

    ``alpha`` -> ``opacity`` (canonical)
    ``accessibility_state_checked`` -> ``accessibility_checked``
    ``accessibility_state_selected`` -> ``accessibility_selected``
    """
    result = dict(props)

    # ACCESSIBILITY-X: Canonicalize accessibility wire prop names
    # so that both accessibility_checked and accessibility_state_checked
    # converge to the canonical accessibility_checked slot.
    if "accessibility_state_checked" in result:
        if "accessibility_checked" not in result:
            result["accessibility_checked"] = result.pop("accessibility_state_checked")
        else:
            result.pop("accessibility_state_checked")  # canonical wins
    if "accessibility_state_selected" in result:
        if "accessibility_selected" not in result:
            result["accessibility_selected"] = result.pop("accessibility_state_selected")
        else:
            result.pop("accessibility_state_selected")  # canonical wins

    if "alpha" in result:
        existing_opacity = result.get("opacity")
        alpha_val = result.pop("alpha")
        # Only raise if opacity was also explicitly set to a different value.
        # If opacity is just the default, alpha takes precedence.
        if existing_opacity is not None and existing_opacity != alpha_val:
            # Check if existing_opacity is the default — if so, override it
            opacity_default = resolve_prop("opacity")
            if opacity_default is None or existing_opacity != opacity_default.default:
                raise ValueError(
                    "Conflicting alpha and opacity: both set to different values"
                )
        result["opacity"] = alpha_val
    return result


def _default_for(prop_name: str) -> Any:
    """Return the canonical default of a core prop, or None."""
    spec = resolve_prop(prop_name)
    return None if spec is None else spec.default


def _resolve_shorthands(props: dict[str, Any]) -> dict[str, Any]:
    """Resolve shorthand props into independent canonical slots.

    ``padding`` -> ``padding_top/bottom/start/end``
    ``corner_radius`` -> four corner props
    ``size`` -> ``width`` + ``height`` (rejected for now, raise)
    """
    result = dict(props)

    # padding shorthand
    if "padding" in result:
        p = result.pop("padding")
        validate_non_negative(p, name="padding")
        for edge in ("padding_top", "padding_bottom", "padding_start", "padding_end"):
            if edge not in result or result[edge] == _default_for(edge):
                result[edge] = p

    # corner_radius shorthand
    if "corner_radius" in result:
        r = result.pop("corner_radius")
        validate_non_negative(r, name="corner_radius")
        for corner in (
            "corner_radius_top_left",
            "corner_radius_top_right",
            "corner_radius_bottom_right",
            "corner_radius_bottom_left",
        ):
            if corner not in result or result[corner] == _default_for(corner):
                result[corner] = r

    # size shorthand — reject (not yet supported)
    if "size" in result:
        raise ValueError(
            "The 'size' shorthand is not yet supported. Use 'width' and 'height' separately."
        )

    return result


# ---------------------------------------------------------------------------
# Dash array normalization
# ---------------------------------------------------------------------------

_DASH_PROPS = frozenset({"stroke_dash_array"})


def _normalize_dash_arrays(props: dict[str, Any]) -> dict[str, Any]:
    """Convert user-facing dash array strings into canonical numeric tuples.

    Accepted forms:
      - Already a tuple/list of positive numbers → converted to tuple
      - String like ``"4,8"`` → parsed to ``(4.0, 8.0)``
      - String ``"full"`` → kept as the special string ``"full"`` (PathView resolves it)
      - JSONArray-like list → converted to tuple
    """
    result = dict(props)
    for name in _DASH_PROPS:
        value = result.get(name)
        if value is None:
            continue
        if isinstance(value, tuple):
            # Already canonical — validate it's a valid dash tuple
            if not is_valid_dash_array(value):
                raise ValueError(
                    f"{name} must be an even-length tuple of positive numbers, got {value!r}"
                )
            continue
        if isinstance(value, list):
            # Convert JSONArray-originated list to tuple
            result[name] = tuple(value)
            if not is_valid_dash_array(result[name]):
                raise ValueError(
                    f"{name} must be an even-length list of positive numbers, got {value!r}"
                )
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                # Empty string → remove (no dash)
                del result[name]
                continue
            if stripped.lower() == "full":
                # Keep "full" as-is — PathView resolves to [pathLength, pathLength]
                result[name] = "full"
                continue
            parts = [p.strip() for p in stripped.split(",")]
            nums: list[float] = []
            for i, part in enumerate(parts):
                try:
                    n = float(part)
                except (ValueError, TypeError):
                    raise ValueError(
                        f"{name} must be comma-separated numbers, got {stripped!r} "
                        f"(part {i}: {part!r})"
                    )
                if not math.isfinite(n) or n <= 0:
                    raise ValueError(
                        f"{name}[{i}] must be a positive finite number, got {n}"
                    )
                nums.append(n)
            if len(nums) % 2 != 0:
                raise ValueError(
                    f"{name} must have an even number of values, got {len(nums)}"
                )
            result[name] = tuple(nums)
            continue
        # Fall through: unknown type will be caught by schema validation
    return result


# ---------------------------------------------------------------------------
# Decoration lowering
# ---------------------------------------------------------------------------

def _lower_decoration(deco_value: Any, kind: str) -> dict[str, Any]:
    """Lower a Decoration value into a canonical prop layer (plain dict).

    Supported: solid rectangle fill color, stroke (without dash), corner radii,
    shadow elevation, ripple color. Rejects: unknown top-level fields,
    gradients, dashed strokes, non-rectangle shapes, translation_z, unbounded
    ripple (MODEL-02). Precedence with explicit props is decided by the merge,
    not here.
    """
    deco_dict = _styling_to_dict(deco_value, name="Decoration")
    values: dict[str, Any] = {}

    _KNOWN_DECO_KEYS = {"shape", "shadow", "ripple"}
    for key in deco_dict:
        if key not in _KNOWN_DECO_KEYS:
            raise ValueError(
                f"Unknown Decoration field {key!r}. "
                f"Supported fields: {', '.join(sorted(_KNOWN_DECO_KEYS))}"
            )

    shape = deco_dict.get("shape")
    if shape is not None:
        if not isinstance(shape, (dict, FrozenMap)):
            raise TypeError("Decoration.shape must be a Shape or dict")
        shape = dict(shape)
        shape_kind = shape.get("kind")
        if shape_kind not in ("rectangle", None):
            raise ValueError(
                f"Decoration shape kind {shape_kind!r} is not yet supported. "
                "Only rectangle shapes are supported."
            )

        fill = shape.get("fill")
        if fill is not None:
            fill_color = _fill_to_color(fill)
            if fill_color is not None:
                values["background_color"] = fill_color

        stroke = shape.get("stroke")
        if stroke is not None:
            stroke_dict = _styling_to_dict(stroke, name="Stroke")
            if stroke_dict.get("dash_width") is not None or stroke_dict.get("dash_gap") is not None:
                raise ValueError(
                    "Dashed strokes in Decoration are not yet supported."
                )
            stroke_color = stroke_dict.get("color")
            if stroke_color is not None:
                values["border_color"] = stroke_color
            stroke_width = stroke_dict.get("width")
            if stroke_width is not None:
                values["border_width"] = stroke_width

        corners = shape.get("corners")
        if corners is not None:
            if isinstance(corners, (int, float)):
                corners_dict = {"radius": corners}
            else:
                corners_dict = _styling_to_dict(corners, name="CornerRadius")
            for corner_name, canon_name in [
                ("top_left", "corner_radius_top_left"),
                ("top_right", "corner_radius_top_right"),
                ("bottom_right", "corner_radius_bottom_right"),
                ("bottom_left", "corner_radius_bottom_left"),
            ]:
                corner_val = corners_dict.get(corner_name) or corners_dict.get("radius")
                if corner_val is not None:
                    values[canon_name] = corner_val

    shadow = deco_dict.get("shadow")
    if shadow is not None:
        shadow_dict = _styling_to_dict(shadow, name="Shadow")
        elevation = shadow_dict.get("elevation")
        if elevation is not None:
            values["elevation"] = elevation
        translation_z = shadow_dict.get("translation_z")
        if translation_z is not None:
            raise ValueError(
                "Shadow.translation_z is not yet supported."
            )

    ripple = deco_dict.get("ripple")
    if ripple is not None:
        ripple_dict = _styling_to_dict(ripple, name="Ripple")
        ripple_color = ripple_dict.get("color")
        if ripple_color is not None:
            values["ripple_color"] = ripple_color
        bounded = ripple_dict.get("bounded")
        if bounded is False:
            raise ValueError("Unbounded ripple is not yet supported.")

    return _normalize_layer(values)


def _styling_to_dict(value: Any, *, name: str) -> dict[str, Any]:
    """Convert a styling dataclass, dict, or FrozenMap to a plain dict."""
    if isinstance(value, (dict, FrozenMap)):
        return dict(value)
    if hasattr(value, "to_props"):
        return value.to_props()
    raise TypeError(f"{name} must be a {name} or dict, got {type(value).__name__}")


def _fill_to_color(fill: Any) -> str | None:
    """Extract color from a Fill. Rejects gradients."""
    if isinstance(fill, str):
        return fill
    if isinstance(fill, (dict, FrozenMap)):
        d = dict(fill)
        kind = d.get("kind", "solid")
        if kind != "solid":
            raise ValueError(
                f"Fill kind {kind!r} (gradients) is not yet supported."
            )
        return d.get("color")
    if hasattr(fill, "to_props"):
        d = fill.to_props()
        if d.get("kind", "solid") != "solid":
            raise ValueError("Gradient fills are not yet supported.")
        return d.get("color")
    return None
