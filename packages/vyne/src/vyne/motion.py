"""Unified Python-owned animation presentation model.

This module defines the canonical animation policy layer for Vyne.
Python owns target identity, value domain, tween/spring parameters,
retarget velocity policy, and cancel/settle semantics.  Kotlin provides
one frame clock/numerical integration engine with View and Canvas adapters.

Key design:
- ``PresentationSlot`` is a stable identity for any animatable property:
  a View property (alpha, scale_x, ...) or a Canvas operation numeric field
  (fill alpha, stroke width, circle radius, ...).
- ``MotionSpec`` is a Python-owned specification: tween or spring.
- ``MotionCommand`` is the instruction sent to the Kotlin engine:
  SetTarget or Cancel.
- ``CanvasOpIdentity`` provides stable string-based operation identifiers
  that survive insert, reorder, and removal of sibling operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


# ── Stable slot identity ────────────────────────────────────────────


@dataclass(frozen=True)
class PresentationSlot:
    """Stable identity for one animatable property.

    For View properties: ``node_id`` is the view's integer ID, ``slot_id``
    is ``None``, and ``property`` is the property name (e.g. "alpha").

    For Canvas operations: ``node_id`` is the Canvas view's ID, ``slot_id``
    is a stable string identifier for the operation (e.g. "op3"), and
    ``property`` is the numeric field within that operation
    (e.g. "fill.color.alpha").
    """

    node_id: int
    property: str
    slot_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, int) or self.node_id <= 0:
            raise ValueError("PresentationSlot node_id must be a positive integer")
        if not isinstance(self.property, str) or not self.property.strip():
            raise ValueError("PresentationSlot property must be a non-empty string")

    def to_key(self) -> str:
        """Return a wire-stable key for this slot.

        The Kotlin engine uses this key to match commands to active transitions.
        """
        if self.slot_id is not None:
            return f"view:{self.node_id}:slot:{self.slot_id}:{self.property}"
        return f"view:{self.node_id}:prop:{self.property}"


# ── Motion specifications ───────────────────────────────────────────


class RetargetPolicy(Enum):
    """How an in-flight animation behaves when retargeted."""

    RESTART = auto()       # Start from the retarget point (implicit from-value).
    MAINTAIN_VELOCITY = auto()  # Carry forward current velocity into the new spec.
    SNAP_TO_END = auto()   # Jump to current target, then start new animation.
    IGNORE = auto()        # Let the current animation finish; ignore the new target.


@dataclass(frozen=True)
class Tween:
    """Tween animation specification.

    A tween interpolates from a start value to a target value over a fixed
    duration using a named easing curve.
    """

    duration_ms: int
    easing: str = "ease_out"
    retarget: RetargetPolicy = RetargetPolicy.RESTART

    def __post_init__(self) -> None:
        if (
            not isinstance(self.duration_ms, int)
            or isinstance(self.duration_ms, bool)
            or self.duration_ms < 0
        ):
            raise ValueError("Tween duration_ms must be a non-negative integer")
        valid_easings = {
            "linear", "ease_in", "ease_out", "ease_in_out", "overshoot", "bounce",
        }
        if self.easing not in valid_easings:
            raise ValueError(
                f"Tween easing must be one of {sorted(valid_easings)}, "
                f"got {self.easing!r}"
            )


@dataclass(frozen=True)
class Spring:
    """Spring-based physics animation specification.

    Uses a damped harmonic oscillator model parameterized by stiffness and
    damping ratio.  The Kotlin engine integrates the physics each frame.

    ``rest_value_threshold`` and ``rest_velocity_threshold`` define when the
    spring is considered settled and the animation can be removed.
    """

    stiffness: float = 380.0
    damping_ratio: float = 0.8
    rest_value_threshold: float = 0.01
    rest_velocity_threshold: float = 0.01
    retarget: RetargetPolicy = RetargetPolicy.MAINTAIN_VELOCITY

    def __post_init__(self) -> None:
        for name, value in [
            ("stiffness", self.stiffness),
            ("damping_ratio", self.damping_ratio),
        ]:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"Spring.{name} must be a number")
            if not __import__("math").isfinite(value) or value <= 0:
                raise ValueError(f"Spring.{name} must be positive and finite")
        for name, value in [
            ("rest_value_threshold", self.rest_value_threshold),
            ("rest_velocity_threshold", self.rest_velocity_threshold),
        ]:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"Spring.{name} must be a number")
            if not __import__("math").isfinite(value) or value < 0:
                raise ValueError(f"Spring.{name} must be non-negative and finite")


MotionSpec = Tween | Spring


# ── Motion commands ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SetTarget:
    """Instruct the native engine to animate a slot through one or more targets.

    If ``from_value`` is ``None``, the engine reads the current live value
    from the View or Canvas operation, enabling smooth mid-animation reversal.
    ``keyframes`` are visited in order after ``target``; they are one native
    timeline, not a series of immediately replacing commands.

    ``animation_id`` is allocated by :class:`Runtime` for public animations.
    Zero is reserved for framework-owned declarative target streams which do
    not publish lifecycle callbacks.
    """

    slot: PresentationSlot
    spec: MotionSpec
    target: float
    from_value: float | None = None
    animation_id: int = 0
    keyframes: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.animation_id, int)
            or isinstance(self.animation_id, bool)
            or self.animation_id < 0
        ):
            raise ValueError("SetTarget.animation_id must be a non-negative integer")
        if not isinstance(self.target, (int, float)) or isinstance(self.target, bool):
            raise TypeError("SetTarget.target must be a number")
        if not __import__("math").isfinite(self.target):
            raise ValueError("SetTarget.target must be finite")
        if self.from_value is not None:
            if not isinstance(self.from_value, (int, float)) or isinstance(
                self.from_value, bool
            ):
                raise TypeError("SetTarget.from_value must be a number or None")
            if not __import__("math").isfinite(self.from_value):
                raise ValueError("SetTarget.from_value must be finite")
        if not isinstance(self.keyframes, tuple):
            raise TypeError("SetTarget.keyframes must be a tuple")
        for value in self.keyframes:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError("SetTarget keyframes must be numbers")
            if not __import__("math").isfinite(value):
                raise ValueError("SetTarget keyframes must be finite")

    @property
    def targets(self) -> tuple[float, ...]:
        """All native destinations in timeline order."""
        return (float(self.target), *(float(value) for value in self.keyframes))


@dataclass(frozen=True)
class Cancel:
    """Cancel an animation for a slot.

    A non-zero ``animation_id`` makes cancellation generation-safe: a stale
    handle cannot cancel a newer animation which has replaced it.
    """

    slot: PresentationSlot
    animation_id: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.animation_id, int)
            or isinstance(self.animation_id, bool)
            or self.animation_id < 0
        ):
            raise ValueError("Cancel.animation_id must be a non-negative integer")


@dataclass(frozen=True)
class DriverSetTarget:
    """Animate a persistent numeric driver rather than one presentation slot.

    ``anchor`` is a currently mounted binding used for lifecycle routing and
    transactional validation.  The native engine animates ``driver_id`` once;
    every View/Canvas expression bound to that driver is evaluated from the
    same live value on each frame.
    """

    driver_id: int
    anchor: PresentationSlot
    spec: MotionSpec
    target: float
    from_value: float | None = None
    animation_id: int = 0
    keyframes: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.driver_id, int)
            or isinstance(self.driver_id, bool)
            or self.driver_id <= 0
        ):
            raise ValueError("DriverSetTarget.driver_id must be a positive integer")
        SetTarget(
            slot=self.anchor,
            spec=self.spec,
            target=self.target,
            from_value=self.from_value,
            animation_id=self.animation_id,
            keyframes=self.keyframes,
        )

    @property
    def targets(self) -> tuple[float, ...]:
        return (float(self.target), *(float(value) for value in self.keyframes))

    @property
    def driver_key(self) -> str:
        return f"driver:{self.driver_id}"


@dataclass(frozen=True)
class DriverCancel:
    """Generation-safe cancellation for a persistent numeric driver."""

    driver_id: int
    anchor: PresentationSlot
    animation_id: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.driver_id, int)
            or isinstance(self.driver_id, bool)
            or self.driver_id <= 0
        ):
            raise ValueError("DriverCancel.driver_id must be a positive integer")
        if (
            not isinstance(self.animation_id, int)
            or isinstance(self.animation_id, bool)
            or self.animation_id < 0
        ):
            raise ValueError("DriverCancel.animation_id must be a non-negative integer")

    @property
    def driver_key(self) -> str:
        return f"driver:{self.driver_id}"


MotionCommand = SetTarget | Cancel | DriverSetTarget | DriverCancel


# ── Canvas operation stable identity ─────────────────────────────────


class CanvasOpIdentity:
    """Provider of stable, string-based identifiers for Canvas display-list ops.

    The current Canvas animation model uses list-index or dictionary-path
    identity (e.g. ``[2, "fill", "alpha"]``).  Those paths break when
    operations are inserted, removed, or reordered.

    This class assigns a stable ``op_id`` (e.g. ``"op3"``) to every Canvas
    operation that carries an animatable numeric field.  The op_id is embedded
    in the operation dict under a reserved key ``_vyne_op_id``, and the Kotlin
    engine uses it instead of structural path to locate and animate the field.

    When Python lowers a Canvas element it calls ``stabilize(draw_list)``.
    Identity is derived from semantic content while animated target/settings
    are replaced by a stable placeholder, so changing a target does not replace
    the native presentation slot.
    """

    RESERVED_ID_KEY = "_vyne_op_id"

    @staticmethod
    def stabilize(
        draw_list: list[dict],
    ) -> list[dict]:
        """Assign stable operation IDs to every operation in ``draw_list``.

        Operations that carry an existing ID retain it.

        The ID is based on a content hash, making it deterministic across
        calls for the same operation content.

        Returns the draw list with ``_vyne_op_id`` set on each operation dict.
        """
        import hashlib
        import json

        from collections.abc import Mapping, Sequence

        def identity_value(value: object) -> object:
            if (
                isinstance(value, Mapping)
                and (
                    value.get("__vyne_animated_value__") is True
                    or value.get("__vyne_animated_node__") is True
                )
            ):
                # Target and motion settings change over time; neither is the
                # semantic identity of the drawing operation.
                return {"__vyne_animated_slot__": True}
            if isinstance(value, Mapping):
                return {
                    str(key): identity_value(item)
                    for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                    if key != CanvasOpIdentity.RESERVED_ID_KEY
                }
            if isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                return [identity_value(item) for item in value]
            return value

        result: list[dict] = []
        occurrences: dict[str, int] = {}

        for op in draw_list:
            op = dict(op)
            existing = op.get(CanvasOpIdentity.RESERVED_ID_KEY)
            if isinstance(existing, str) and existing:
                result.append(op)
                continue

            # Generate a deterministic ID based on operation content.
            # The hash ensures same content → same ID across calls.
            op_kind = op.get("kind", "unknown")
            canonical = json.dumps(
                identity_value(op),
                sort_keys=True,
                default=str,
            )
            content_hash = hashlib.sha256(canonical.encode()).hexdigest()[:12]
            occurrence = occurrences.get(content_hash, 0)
            occurrences[content_hash] = occurrence + 1
            op[CanvasOpIdentity.RESERVED_ID_KEY] = (
                f"{op_kind}_{content_hash}_{occurrence}"
            )
            result.append(op)

        return result

    @staticmethod
    def animatable_fields() -> dict[str, list[str]]:
        """Return the animatable numeric fields for each Canvas operation kind.

        Maps operation kind to a list of dot-separated field paths that can
        be animated.
        """
        return {
            "rect": [
                "x", "y", "width", "height",
                "opacity", "stroke_width", "dash_offset",
            ],
            "round_rect": [
                "x", "y", "width", "height", "radius",
                "opacity", "stroke_width", "dash_offset",
            ],
            "circle": [
                "cx", "cy", "r",
                "opacity", "stroke_width", "dash_offset",
            ],
            "line": [
                "x1", "y1", "x2", "y2",
                "opacity", "stroke_width", "dash_offset",
            ],
            "path": [
                "trim_start", "trim_end",
                "opacity", "stroke_width", "dash_offset",
            ],
        }


# ── Serialization helpers ────────────────────────────────────────────

def motion_command_to_dict(cmd: MotionCommand) -> dict:
    """Lower a MotionCommand to a logical renderer operation."""
    if isinstance(cmd, (SetTarget, DriverSetTarget)):
        slot = cmd.slot if isinstance(cmd, SetTarget) else cmd.anchor
        result: dict = {
            "op": (
                "motion_set_target"
                if isinstance(cmd, SetTarget)
                else "motion_driver_set_target"
            ),
            "animation_id": cmd.animation_id,
            "slot_key": (
                slot.to_key()
                if isinstance(cmd, SetTarget)
                else cmd.driver_key
            ),
            "node_id": slot.node_id,
            "property": slot.property,
            "spec_type": "spring" if isinstance(cmd.spec, Spring) else "tween",
            "targets": list(cmd.targets),
        }
        if isinstance(cmd, DriverSetTarget):
            result["driver_id"] = cmd.driver_id
        elif slot.slot_id is not None:
            result["slot_id"] = slot.slot_id
        if cmd.from_value is not None:
            result["from_value"] = cmd.from_value

        if isinstance(cmd.spec, Tween):
            result["duration_ms"] = cmd.spec.duration_ms
            result["easing"] = cmd.spec.easing
            result["retarget"] = cmd.spec.retarget.name.lower()
        else:
            result["stiffness"] = cmd.spec.stiffness
            result["damping_ratio"] = cmd.spec.damping_ratio
            result["rest_value_threshold"] = cmd.spec.rest_value_threshold
            result["rest_velocity_threshold"] = cmd.spec.rest_velocity_threshold
            result["retarget"] = cmd.spec.retarget.name.lower()
        return result

    if isinstance(cmd, Cancel):
        return {
            "op": "motion_cancel",
            "slot_key": cmd.slot.to_key(),
            "animation_id": cmd.animation_id,
        }

    if isinstance(cmd, DriverCancel):
        return {
            "op": "motion_driver_cancel",
            "slot_key": cmd.driver_key,
            "driver_id": cmd.driver_id,
            "animation_id": cmd.animation_id,
        }

    raise TypeError(f"Unknown MotionCommand type: {type(cmd)}")
