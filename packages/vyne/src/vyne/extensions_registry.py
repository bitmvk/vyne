"""Host-synced extension contract tables.

Extensions do not register on the Python side. The Kotlin ``ElementRegistry``
is the single source of truth: at startup the host is queried for
``kind -> (props, events, container)`` and the tables are synced here via
:func:`sync_from_host`. Core ``schema_v2`` is consulted first; extension
tables fill the gaps. This keeps one contract, one code path, and makes
Python/Kotlin drift impossible by construction.

The synced contract is ONE immutable value (:class:`ExtensionContracts`),
replaced atomically by :func:`sync_from_host` / :func:`restore` — there are
no partially-updated projections to keep in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Mapping

from vyne.spec.model import EventSpec, KindSpec, PropSpec, ValueSpec
from vyne.spec.schema_v2 import (
    ALL_PROPS,
    ANIMATABLE_PROPS,
    EVENT_SPECS,
    PRIMITIVE_KINDS,
    PROPS_BY_KIND,
    is_animatable_prop_spec,
)


# ---------------------------------------------------------------------------
# Public value types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ExtensionNumericProp:
    """Bridge-safe numeric description for one extension prop.

    Kotlin's typed ``floatProp`` helper emits this information.  Python uses
    it to synthesize the same scalar ``ValueSpec`` core numeric props use,
    which makes the prop animatable automatically — no animation-specific
    registration exists on either side.
    """

    default: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.default, bool)
            or not isinstance(self.default, (int, float))
            or not math.isfinite(self.default)
        ):
            raise TypeError("ExtensionNumericProp.default must be a finite number")
        for name, value in (("minimum", self.minimum), ("maximum", self.maximum)):
            if value is not None:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise TypeError(
                        f"ExtensionNumericProp.{name} must be a finite number or None"
                    )
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("ExtensionNumericProp.minimum must be <= maximum")

    @classmethod
    def from_bridge(cls, value: Any) -> "ExtensionNumericProp":
        """Decode ``[default, minimum, maximum]`` from the Kotlin bridge."""
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise TypeError(
                "Extension numeric prop bridge value must be "
                f"[default, minimum, maximum], got {value!r}"
            )
        default, minimum, maximum = value
        if (
            isinstance(default, bool)
            or not isinstance(default, (int, float))
            or not math.isfinite(default)
        ):
            raise TypeError(
                f"Extension numeric prop default must be a finite number, got {default!r}"
            )
        for name, item in (("minimum", minimum), ("maximum", maximum)):
            if item is not None and (
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(item)
            ):
                raise TypeError(
                    f"Extension numeric prop {name} must be a finite number or null, "
                    f"got {item!r}"
                )
        return cls(float(default), minimum, maximum)


@dataclass(frozen=True, slots=True)
class ExtensionKindInfo:
    """Bridge-safe description of one extension kind from the host.

    ``container`` mirrors the Kotlin ElementSpec: False means the native
    view is a leaf (no children allowed); True means it accepts children.
    ``numeric_props`` contains the typed float props that are automatically
    scalar-animatable. Invariants are enforced at construction
    (``__post_init__``) and the bridge shape is validated by
    :meth:`from_bridge` — the ONLY foreign-shape adapter.
    """

    props: frozenset[str] = frozenset()
    events: frozenset[str] = frozenset()
    container: bool = False
    numeric_props: Mapping[str, ExtensionNumericProp] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not isinstance(self.props, frozenset) or not all(
            isinstance(p, str) for p in self.props
        ):
            raise TypeError("ExtensionKindInfo.props must be a frozenset of strings")
        if not isinstance(self.events, frozenset) or not all(
            isinstance(e, str) for e in self.events
        ):
            raise TypeError("ExtensionKindInfo.events must be a frozenset of strings")
        if type(self.container) is not bool:
            raise TypeError("ExtensionKindInfo.container must be an exact bool")
        if not isinstance(self.numeric_props, Mapping) or not all(
            isinstance(name, str) and isinstance(info, ExtensionNumericProp)
            for name, info in self.numeric_props.items()
        ):
            raise TypeError(
                "ExtensionKindInfo.numeric_props must map strings to "
                "ExtensionNumericProp"
            )
        unknown = frozenset(self.numeric_props) - self.props
        if unknown:
            raise ValueError(
                f"Extension numeric props must be declared in props; "
                f"unknown names: {sorted(unknown)!r}"
            )

    @classmethod
    def from_bridge(cls, value: Any) -> "ExtensionKindInfo":
        """The ONLY adapter for the Kotlin bridge shape.

        The host emits each kind as ``[props, events, [container]]``.
        Hosts with typed numeric props append a fourth entry:
        ``[props, events, [container], numeric_props]`` where
        ``numeric_props`` maps a prop name to ``[default, min, max]``.
        Anything else fails loudly here — never later with a wrong value
        (e.g. ``bool([False])`` is True).
        """
        if not isinstance(value, (list, tuple)) or len(value) not in {3, 4}:
            raise TypeError(
                "Extension kind bridge value must be [props, events, [container]] "
                "with an optional numeric-props entry, "
                f"got {value!r}"
            )
        props, events, container = value[0], value[1], value[2]
        if not isinstance(props, (list, tuple)) or not all(
            type(p) is str for p in props
        ):
            raise TypeError(
                f"Extension kind props must be a list of exact strings, got {props!r}"
            )
        if not isinstance(events, (list, tuple)) or not all(
            type(e) is str for e in events
        ):
            raise TypeError(
                f"Extension kind events must be a list of exact strings, got {events!r}"
            )
        if (
            not isinstance(container, (list, tuple))
            or len(container) != 1
            or type(container[0]) is not bool
        ):
            raise TypeError(
                "Extension kind container must be a singleton list holding an "
                f"exact bool, got {container!r}"
            )
        numeric_props: dict[str, ExtensionNumericProp] = {}
        if len(value) == 4:
            raw_numeric = value[3]
            if not isinstance(raw_numeric, Mapping):
                raise TypeError(
                    "Extension numeric props must be a mapping, "
                    f"got {raw_numeric!r}"
                )
            for name, raw_info in raw_numeric.items():
                if not isinstance(name, str):
                    raise TypeError(
                        f"Extension numeric prop name must be a string, got {name!r}"
                    )
                numeric_props[name] = (
                    raw_info
                    if isinstance(raw_info, ExtensionNumericProp)
                    else ExtensionNumericProp.from_bridge(raw_info)
                )
        return cls(
            props=frozenset(props),
            events=frozenset(events),
            container=container[0],
            numeric_props=MappingProxyType(numeric_props),
        )


@dataclass(frozen=True, slots=True)
class ExtensionContracts:
    """One immutable snapshot of the synced extension contract."""

    kinds: Mapping[str, ExtensionKindInfo] = field(default_factory=dict)
    kind_specs: Mapping[str, KindSpec] = field(default_factory=dict)
    event_names: frozenset[str] = frozenset()
    prop_specs: Mapping[str, Mapping[str, PropSpec]] = field(default_factory=dict)


_EMPTY = ExtensionContracts()


# ---------------------------------------------------------------------------
# Module state (one value; swapped atomically)
# ---------------------------------------------------------------------------

_contracts: ExtensionContracts = _EMPTY


# ---------------------------------------------------------------------------
# Core-derived constants
# ---------------------------------------------------------------------------

# Generic props apply to every kind (core and extension). Derived as the
# intersection of all core kind prop sets — the same derivation the Kotlin
# side uses for its GENERIC_PROPS, so both sides agree.
GENERIC_PROPS: frozenset[str] = frozenset.intersection(*PROPS_BY_KIND.values())

# Core event-handler prop map (``on_click`` -> ``click``), DERIVED from the
# authoritative EVENT_SPECS — one source, no hand-maintained copy. Extension
# event handler props are derived from the synced event names via the ``on_``
# prefix convention.
CORE_EVENT_PROPS: dict[str, str] = {
    f"on_{name}": name for name in EVENT_SPECS
}


def _core_event_applies(event: str, kind: str) -> bool:
    """Per-kind applicability from EventSpec.applies_to (empty = all kinds)."""
    spec = EVENT_SPECS.get(event)
    return spec is not None and (not spec.applies_to or kind in spec.applies_to)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_known_prop(name: str) -> bool:
    """True for any core prop or any synced extension prop name.

    Op-level validation cannot see the target kind (kind lives on the
    create op), so this is the coarsest correct net; the Kotlin preflight
    validates per-kind.
    """
    if name in ALL_PROPS:
        return True
    return any(name in info.props for info in _contracts.kinds.values())


def _build_contracts(kinds: Mapping[str, ExtensionKindInfo]) -> ExtensionContracts:
    """Prebuild the immutable projections from one validated kind map."""
    kind_specs: dict[str, KindSpec] = {}
    event_names: set[str] = set()
    prop_specs: dict[str, Mapping[str, PropSpec]] = {}
    for kind, info in kinds.items():
        # A leaf extension kind cannot parent children (its native view is
        # not a ViewGroup); a container is unrestricted.
        max_children = 0 if not info.container else None
        kind_specs[kind] = KindSpec(
            kind=kind,
            max_children=max_children,
        )
        event_names.update(info.events)
        built_props: dict[str, PropSpec] = {}
        for name, numeric in info.numeric_props.items():
            built_props[name] = PropSpec(
                name=name,
                value=ValueSpec(
                    exact_types=(int, float),
                    finite=True,
                    min_value=numeric.minimum,
                    max_value=numeric.maximum,
                ),
                default=numeric.default,
                animatable=True,
                drop_default=True,
            )
        prop_specs[kind] = MappingProxyType(built_props)
    return ExtensionContracts(
        kinds=dict(kinds),
        kind_specs=kind_specs,
        event_names=frozenset(event_names),
        prop_specs=MappingProxyType(prop_specs),
    )


def sync_from_host(kinds: Mapping[str, Any]) -> None:
    """Replace the extension tables from a host query result.

    *kinds* maps a kind name to either an :class:`ExtensionKindInfo` or a
    ``(props, events)`` / ``(props, events, container)`` sequence. Previous
    tables are fully replaced (a new startup must never inherit stale kinds).
    """
    built: dict[str, ExtensionKindInfo] = {}
    for kind, info in kinds.items():
        if kind in PRIMITIVE_KINDS:
            raise ValueError(
                f"Extension kind {kind!r} collides with a core primitive kind"
            )
        if isinstance(info, ExtensionKindInfo):
            built[kind] = info
        else:
            built[kind] = ExtensionKindInfo.from_bridge(info)
    # All inputs validated: commit atomically (a failed sync must never
    # corrupt the active tables).
    global _contracts
    _contracts = _build_contracts(built)


def snapshot() -> ExtensionContracts:
    """Immutable copy of the active contracts (candidate promotion/restore)."""
    return _contracts


def restore(snapshot_contracts: ExtensionContracts) -> None:
    """Restore the exact prior contracts (rejection / startup failure)."""
    global _contracts
    _contracts = snapshot_contracts


def resolve_kind(kind: str) -> KindSpec | None:
    """Return the kind spec (core first, then extensions), or None."""
    core = PRIMITIVE_KINDS.get(kind)
    if core is not None:
        return core
    return _contracts.kind_specs.get(kind)


def props_by_kind(kind: str) -> frozenset[str]:
    """All valid prop names for a kind (core or extension)."""
    core = PROPS_BY_KIND.get(kind)
    if core is not None:
        return core
    info = _contracts.kinds.get(kind)
    if info is None:
        return frozenset()
    return frozenset(GENERIC_PROPS) | info.props


def resolve_prop(name: str) -> Any:
    """Return the global core PropSpec for *name*, or None.

    Prefer :func:`resolve_prop_for_kind` for kind-aware decisions.  This
    global lookup remains for protocol code that cannot see the target kind.
    """
    return ALL_PROPS.get(name)


def resolve_prop_for_kind(kind: str, name: str) -> PropSpec | None:
    """Return the PropSpec that governs *name* on *kind*, or None.

    Core kinds use schema_v2.  Extension kinds inherit the core generic
    props (width, opacity, padding, ...) and may additionally contribute
    typed numeric props synced from Kotlin's ``floatProp`` declarations.
    """
    if kind in PRIMITIVE_KINDS:
        if name in PROPS_BY_KIND.get(kind, frozenset()):
            return ALL_PROPS.get(name)
        return None
    info = _contracts.kinds.get(kind)
    if info is None:
        return None
    if name in GENERIC_PROPS:
        return ALL_PROPS.get(name)
    return _contracts.prop_specs.get(kind, {}).get(name)


def is_animatable_prop(kind: str, name: str) -> bool:
    """True when *name* can be driven by the scalar animation engine on *kind*."""
    spec = resolve_prop_for_kind(kind, name)
    return spec is not None and is_animatable_prop_spec(spec)


def animatable_prop_names() -> frozenset[str]:
    """Global animatable-name net for protocol-level structural checks.

    Per-kind applicability is enforced later by the Runtime and the Kotlin
    preflight; this function intentionally over-approximates.
    """
    names = set(ANIMATABLE_PROPS)
    for specs in _contracts.prop_specs.values():
        names.update(specs)
    return frozenset(names)


def resolve_event(name: str) -> EventSpec | None:
    """Return the event spec (core first, then extensions), or None.

    Extension events have no declared payload fields: the returned spec
    truthfully describes itself as an open-payload event.
    """
    core = EVENT_SPECS.get(name)
    if core is not None:
        return core
    if name in _contracts.event_names:
        return EventSpec(name=name, open_payload=True)
    return None


def is_event_prop(prop_name: str, kind: str | None = None) -> bool:
    """True when *prop_name* is a recognized event-handler prop.

    Core event props are recognized globally (the schema already restricts
    their kinds). Extension event props are per-kind: ``on_<event>`` is only
    valid on a kind whose synced event set contains ``<event>`` — matching
    the Kotlin ``ElementSpec.events`` map.
    """
    if prop_name in CORE_EVENT_PROPS:
        event = CORE_EVENT_PROPS[prop_name]
        if kind is None:
            return True
        return _core_event_applies(event, kind)
    if not prop_name.startswith("on_"):
        return False
    event = prop_name[3:]
    if kind is None:
        return event in _contracts.event_names
    info = _contracts.kinds.get(kind)
    return info is not None and event in info.events


def event_name_for_prop(prop_name: str, kind: str | None = None) -> str | None:
    """Map an event-handler prop to its event name (core or extension)."""
    core = CORE_EVENT_PROPS.get(prop_name)
    if core is not None:
        if kind is None or _core_event_applies(core, kind):
            return core
        return None
    if is_event_prop(prop_name, kind):
        return prop_name[3:]
    return None
