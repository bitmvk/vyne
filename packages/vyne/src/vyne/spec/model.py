"""Canonical data model definitions for Vyne's v2 schema.

ValueSpec, PropSpec, KindSpec, CanvasOpSpec, and EventSpec describe the
exact shape, types, defaults, limits, and removal behavior for every
primitive widget, property, and display-list operation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# ValueSpec — exact type, nullability, range, enum, dimension, color
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=True)
class ValueSpec:
    """Describes the allowed value domain for one property/field.

    All fields are optional; only the constraints that apply are set.
    ``type_name`` is the Python surface type (``"str"``, ``"int"``, ``"float"``,
    ``"bool"``, ``"tuple"``, ``"FrozenMap"``, ``"dict"``) and is matched
    against the lowered canonical value before commit.
    """

    type_name: str | None = None
    nullable: bool = False
    # Exact Python types accepted
    exact_types: tuple[type, ...] = ()
    # Numeric constraints
    finite: bool = False
    positive: bool = False
    non_negative: bool = False
    min_value: float | int | None = None
    max_value: float | int | None = None
    # Enum restriction
    enum: frozenset[str] | None = None
    # Color validation
    color: bool = False
    # Dimension (Dp | WrapContent | MatchParent) — string representation
    dimension: bool = False
    # Dash array validation (even-length positive numeric tuple)
    dash_array: bool = False
    # FrozenMap with string keys
    string_map: bool = False
    # Collection shape/member contract.  Nested schemas are validated before
    # any domain-specific consumer sees the value.
    item_spec: "ValueSpec | None" = None
    min_items: int | None = None
    max_items: int | None = None
    # Child list — validated separately by the kind spec
    children: bool = False

    def validate(self, value: Any, *, path: str = "value") -> None:
        """Raise TypeError/ValueError if *value* does not conform."""
        from vyne.values import (
            is_finite_number,
            is_valid_color,
            is_valid_dash_array,
            validate_finite,
            validate_positive,
            validate_non_negative,
            FrozenMap,
        )

        if value is None:
            if not self.nullable:
                raise TypeError(f"{path} does not accept null")
            return

        # Animated node markers validate their inner payload against the
        # underlying value contract.
        if isinstance(value, (dict, FrozenMap)) and (
            value.get("__vyne_animated_node__") is True
        ):
            if "value" not in value:
                raise TypeError(f"{path} animated marker requires value")
            self.validate(value["value"], path=f"{path}.value")
            return

        if self.exact_types and type(value) not in self.exact_types:
            expected = " | ".join(t.__name__ for t in self.exact_types)
            raise TypeError(
                f"{path} must be {expected}, got {type(value).__name__}"
            )

        if self.type_name is not None:
            named_types: dict[str, tuple[type, ...]] = {
                "str": (str,),
                "int": (int,),
                "float": (float,),
                "bool": (bool,),
                "tuple": (tuple,),
                "list": (list,),
                "dict": (dict,),
                "FrozenMap": (FrozenMap,),
                "number": (int, float),
            }
            expected_types = named_types.get(self.type_name)
            if expected_types is None:
                raise RuntimeError(f"Unknown schema type_name {self.type_name!r}")
            if type(value) not in expected_types:
                raise TypeError(
                    f"{path} must be {self.type_name}, got {type(value).__name__}"
                )

        is_collection = isinstance(value, (list, tuple, dict, FrozenMap))
        if self.item_spec is not None or self.min_items is not None or self.max_items is not None:
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"{path} must be a list or tuple, got {type(value).__name__}")
            if self.min_items is not None and len(value) < self.min_items:
                raise ValueError(f"{path} must contain at least {self.min_items} items")
            if self.max_items is not None and len(value) > self.max_items:
                raise ValueError(f"{path} must contain at most {self.max_items} items")
            if self.item_spec is not None:
                for index, item in enumerate(value):
                    self.item_spec.validate(item, path=f"{path}[{index}]")

        # Numeric constraints describe this value itself.  Collection members
        # use item_spec; a collection cannot bypass a scalar domain check.
        if (self.finite or self.positive or self.non_negative or
                self.min_value is not None or self.max_value is not None) and is_collection:
            raise TypeError(f"{path} must be a finite number, got {type(value).__name__}")

        if self.finite:
            validate_finite(value, name=path)

        if self.positive:
            validate_positive(value, name=path)

        if self.non_negative:
            validate_non_negative(value, name=path)

        if self.min_value is not None:
            if not is_finite_number(value):
                raise TypeError(f"{path} must be a finite number, got {type(value).__name__}")
            if value < self.min_value:
                raise ValueError(f"{path} must be >= {self.min_value}, got {value}")

        if self.max_value is not None:
            if not is_finite_number(value):
                raise TypeError(f"{path} must be a finite number, got {type(value).__name__}")
            if value > self.max_value:
                raise ValueError(f"{path} must be <= {self.max_value}, got {value}")

        if self.enum is not None:
            if not isinstance(value, str):
                raise TypeError(f"{path} must be a string for enum, got {type(value).__name__}")
            if value not in self.enum:
                raise ValueError(
                    f"{path} must be one of {sorted(self.enum)!r}, got {value!r}"
                )

        if self.color and not is_valid_color(value):
            raise ValueError(
                f"{path} must be #RRGGBB or #RRGGBBAA, got {value!r}"
            )

        if self.dimension:
            # Accept numeric values (dp) and strings (wrap_content, match_parent, Ndp)
            if isinstance(value, (int, float)):
                if isinstance(value, bool):
                    raise TypeError(f"{path} dimension must be a number or string, got bool")
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"{path} dimension must be finite and non-negative, got {value}")
            elif isinstance(value, str):
                if value not in ("wrap_content", "match_parent"):
                    if not value.endswith("dp"):
                        raise ValueError(
                            f"{path} must be 'wrap_content', 'match_parent', or Ndp, got {value!r}"
                        )
                    try:
                        amount = float(value[:-2])
                    except ValueError as exc:
                        raise ValueError(f"{path} has invalid dp value {value!r}") from exc
                    if not math.isfinite(amount) or amount < 0:
                        raise ValueError(f"{path} dimension must be finite and non-negative")
            else:
                raise TypeError(f"{path} dimension must be string or number, got {type(value).__name__}")

        if self.dash_array and not is_valid_dash_array(value):
            # Allow "full" string as PathView-level marker for [pathLength, pathLength]
            if isinstance(value, str) and value == "full":
                return
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"{path} must be an array for dash array")
            raise ValueError(
                f"{path} must be an even-length tuple of positive numbers, got {value!r}"
            )

        if self.string_map and not isinstance(value, FrozenMap):
            raise TypeError(f"{path} must be a FrozenMap (frozen string-key mapping)")


# ---------------------------------------------------------------------------
# PropSpec — one property definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=True)
class PropSpec:
    """Definition of a single property across one or more widget kinds."""

    name: str
    value: ValueSpec
    default: Any = None  # canonical default value
    applies_to: frozenset[str] = field(default_factory=frozenset)
    animatable: bool = False
    removal: Literal["canonical_default"] = "canonical_default"
    # Native Kotlin View property slot for mechanical application.
    # When None the prop is Python-only (lowered away before commit).
    wire_name: str | None = None
    # If True, the prop is removed from the canonical set when its value
    # equals the default — i.e. the wire protocol never sends defaults.
    drop_default: bool = False


# ---------------------------------------------------------------------------
# KindSpec — one widget primitive
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=True)
class KindSpec:
    """Definition of one primitive widget kind."""

    kind: str
    # Accepted child kinds (empty means any / no restriction)
    allowed_children: frozenset[str] = field(default_factory=frozenset)
    min_children: int = 0
    max_children: int | None = None
    # Prop names that are required for this kind
    required: frozenset[str] = field(default_factory=frozenset)
    # All props that apply to this kind (compat: frozenset[str])
    props: frozenset[str] = field(default_factory=frozenset)
    # Event names this kind supports (for code generation)
    events: frozenset[str] = field(default_factory=frozenset)
    # Human-readable, platform-neutral description (for docs generation).
    # Platform factories live in each host registry, never in this schema.
    description: str = ""

    @property
    def leaf(self) -> bool:
        """True if this kind cannot have children (leaf node)."""
        return self.max_children == 0

    @property
    def required_children(self) -> frozenset[str]:
        """Kinds that must appear as children (empty for all)."""
        return frozenset()




# ---------------------------------------------------------------------------
# CanvasOpSpec — one display-list operation
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=True)
class CanvasOpSpec:
    """Definition of one Canvas display-list operation."""

    kind: str
    fields: frozenset[str] = field(default_factory=frozenset)
    required: frozenset[str] = field(default_factory=frozenset)
    field_specs: dict[str, ValueSpec] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# EventSpec — one event type definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=True)
class EventSpec:
    """Definition of one supported event type.

    Each payload field carries an optional ValueSpec for validation,
    an optional controlled-prop mapping (the canonical prop name whose
    native value is acknowledged by this field), and a Kotlin wire name
    for code generation.
    """

    name: str
    payload_fields: frozenset[str] = field(default_factory=frozenset)
    applies_to: frozenset[str] = field(default_factory=frozenset)
    # Per-payload-field metadata for validation and ack extraction.
    # Maps field_name -> ValueSpec for type/domain checking.
    payload_specs: dict[str, ValueSpec] = field(default_factory=dict)
    # Maps payload_field -> canonical_prop_name for controlled-value ack.
    controlled_props: dict[str, str] = field(default_factory=dict)
    # Kotlin wire name for each payload field (for code generation).
    payload_wire_names: dict[str, str] = field(default_factory=dict)
    # True when the payload is open (extension events): no field validation
    # is applied and any bridge-safe payload is accepted. A spec that is
    # neither closed-with-fields nor open means a closed empty payload.
    open_payload: bool = False
    # True when the event is part of the public constructor callback surface
    # (``on_<name>`` props). Internal renderer observations used by the
    # virtual-list controller are protocol contracts, not public constructor
    # callbacks, and set this to False. The flag only controls typing/docs
    # surface; wire behavior and per-kind applicability are unchanged.
    public_callback: bool = True
