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
from typing import Any, Mapping

from vyne.spec.model import EventSpec, KindSpec
from vyne.spec.schema_v2 import ALL_PROPS, EVENT_SPECS, PRIMITIVE_KINDS, PROPS_BY_KIND


# ---------------------------------------------------------------------------
# Public value types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ExtensionKindInfo:
    """Bridge-safe description of one extension kind from the host.

    ``container`` mirrors the Kotlin ElementSpec: False means the native
    view is a leaf (no children allowed); True means it accepts children.
    Invariants are enforced at construction (``__post_init__``) and the
    bridge shape is validated by :meth:`from_bridge` — the ONLY foreign-
    shape adapter.
    """

    props: frozenset[str] = frozenset()
    events: frozenset[str] = frozenset()
    container: bool = False

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

    @classmethod
    def from_bridge(cls, value: Any) -> "ExtensionKindInfo":
        """The ONLY adapter for the Kotlin bridge shape.

        The host emits each kind as exactly ``[props, events, [container]]``:
        props/events are lists of exact strings and container is a singleton
        list holding an exact bool. Anything else fails loudly here — never
        later with a wrong value (e.g. ``bool([False])`` is True).
        """
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise TypeError(
                "Extension kind bridge value must be [props, events, [container]] "
                f"with exactly 3 entries, got {value!r}"
            )
        props, events, container = value
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
        return cls(
            props=frozenset(props),
            events=frozenset(events),
            container=container[0],
        )


@dataclass(frozen=True, slots=True)
class ExtensionContracts:
    """One immutable snapshot of the synced extension contract."""

    kinds: Mapping[str, ExtensionKindInfo] = field(default_factory=dict)
    kind_specs: Mapping[str, KindSpec] = field(default_factory=dict)
    event_names: frozenset[str] = frozenset()


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
    for kind, info in kinds.items():
        # A leaf extension kind cannot parent children (its native view is
        # not a ViewGroup); a container is unrestricted.
        max_children = 0 if not info.container else None
        kind_specs[kind] = KindSpec(
            kind=kind,
            max_children=max_children,
            props=frozenset(GENERIC_PROPS) | info.props,
            events=info.events,
            description="Extension-provided kind",
        )
        event_names.update(info.events)
    return ExtensionContracts(
        kinds=dict(kinds),
        kind_specs=kind_specs,
        event_names=frozenset(event_names),
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
    """Return the core PropSpec for *name*, or None for extension props.

    Extension props declare no value specs: their values are converted
    defensively by the extension's Kotlin handlers. None also means the
    prop is not animatable (the existing animated-value guard rejects
    Animated payloads when no animatable PropSpec exists).
    """
    return ALL_PROPS.get(name)


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
