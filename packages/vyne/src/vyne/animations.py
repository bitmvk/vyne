"""Two-layer animation API for the unified View and Canvas presentation model.

Use :func:`animate` for direct one-off property transitions with no declared
state. Use :class:`Animated` when a persistent driver, derived expressions, or
timeline composition is needed. Both lower to :class:`MotionSpec` commands.
The Kotlin host uses one frame clock and numerical integration engine with
View and Canvas adapters. There is zero Python involvement during frames.

``target`` can be a raw view ID (int), a ``Ref``, or a ``ViewHandle``.
Passing an ``Element`` is no longer supported — identity lives on the
per-mount ``Ref``/``ViewHandle``, not the Element.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, Any, Protocol
from weakref import ReferenceType

from vyne.motion import (
    DriverSetTarget,
    MotionSpec,
    PresentationSlot,
    RetargetPolicy,
    SetTarget,
    Spring,
    Tween,
)

if TYPE_CHECKING:
    from vyne.refs import Ref, ViewHandle
    from vyne.runtime import Runtime

# Wire marker identifying a lowered AnimatedNode payload.  Canvas draw
# operations carry these inline JSON markers; the Kotlin engine resolves
# them through the stable operation identity.
ANIMATED_NODE_MARKER = "__vyne_animated_node__"

# Supported easing curves for tween animations.
_TWEEN_EASINGS = frozenset(
    {"linear", "ease_in", "ease_out", "ease_in_out", "overshoot", "bounce"}
)

# Public retarget policies accepted by animate().
_RETARGET_POLICIES = frozenset(
    {"restart", "maintain_velocity", "snap_to_end", "ignore"}
)

# Public easing names for consumption by tests and documentation.
ANIMATION_EASINGS = _TWEEN_EASINGS

# Canonical primitive properties currently backed by native presentation
# adapters. ``alpha`` remains a public compatibility alias for ``opacity``.
ANIMATABLE_VIEW_PROPERTIES = frozenset({
    "elevation",
    "height",
    "opacity",
    "rotation",
    "rotation_x",
    "rotation_y",
    "scale_x",
    "scale_y",
    "stroke_dash_offset",
    "translation_x",
    "translation_y",
    "width",
})
_PROPERTY_ALIASES = {"alpha": "opacity"}


@dataclass(frozen=True)
class AnimationEvent:
    """A terminal native animation lifecycle notification."""

    animation_id: int
    status: str
    node_id: int
    property: str
    reason: str | None = None


class _AnimationHandle(Protocol):
    @property
    def id(self) -> int: ...

    @property
    def slot(self) -> PresentationSlot: ...

    @property
    def status(self) -> str: ...

    @property
    def reason(self) -> str | None: ...

    @property
    def done(self) -> bool: ...

    def cancel(self) -> bool: ...


class AnimationHandle:
    """Generation-safe handle returned by :func:`animate`.

    The handle tracks terminal native state and can request cancellation from
    an event/render callback. Cancelling an old handle cannot affect a newer
    animation which has taken over the same property.
    """

    def __init__(
        self,
        animation_id: int,
        slot: PresentationSlot,
        runtime: ReferenceType[Runtime],
    ) -> None:
        self.id = animation_id
        self.slot = slot
        self._runtime = runtime
        self._status = "queued"
        self._reason: str | None = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def done(self) -> bool:
        return self._status in {"completed", "cancelled", "rejected"}

    def cancel(self) -> bool:
        """Queue generation-safe native cancellation.

        Returns ``False`` if the animation is already terminal or its Runtime
        no longer exists.
        """
        if self.done:
            return False
        runtime = self._runtime()
        if runtime is None:
            self._finish("cancelled", "runtime_released")
            return False
        return bool(runtime.cancel_animation(self))

    def _mark_running(self) -> None:
        if not self.done:
            self._status = "running"

    def _finish(self, status: str, reason: str | None = None) -> None:
        if self.done:
            return
        self._status = status
        self._reason = reason


class AnimationGroupHandle:
    """One lifecycle handle for a group of native animation timelines."""

    def __init__(
        self,
        children: Sequence[_AnimationHandle] = (),
        *,
        on_complete: Callable[..., Any] | None = None,
        on_cancel: Callable[..., Any] | None = None,
        stop_together: bool = True,
    ) -> None:
        self._children = tuple(children)
        self._on_complete = on_complete
        self._on_cancel = on_cancel
        self._status = "queued"
        self._reason: str | None = None
        self._completed: set[int] = set()
        self._cancelled: set[int] = set()
        self._callback_delivered = False
        self._stop_together = stop_together

    @property
    def id(self) -> int:
        return self._children[0].id if self._children else 0

    @property
    def children(self) -> tuple[_AnimationHandle, ...]:
        return self._children

    @property
    def slot(self) -> PresentationSlot:
        if not self._children:
            raise RuntimeError("Animation group has not started")
        return self._children[0].slot

    @property
    def status(self) -> str:
        if self.done:
            return self._status
        if any(child.status == "running" for child in self._children):
            return "running"
        return "queued"

    @property
    def reason(self) -> str | None:
        if self._reason is None:
            rejected = next(
                (child for child in self._children if child.status == "rejected"),
                None,
            )
            if rejected is not None:
                return rejected.reason
        return self._reason

    @property
    def done(self) -> bool:
        if self._status in {"completed", "cancelled", "rejected"}:
            return True
        if self._children and all(child.done for child in self._children):
            if any(child.status == "rejected" for child in self._children):
                self._status = "rejected"
            elif any(child.status == "cancelled" for child in self._children):
                self._status = "cancelled"
            else:
                self._status = "completed"
            return True
        return False

    def cancel(self) -> bool:
        """Cancel every still-active child generation."""
        cancelled = False
        for child in self._children:
            cancelled = child.cancel() or cancelled
        return cancelled

    def _attach(self, children: Sequence[_AnimationHandle]) -> None:
        if self._children:
            raise RuntimeError("AnimationGroupHandle is already attached")
        self._children = tuple(children)

    def _child_complete(self, event: AnimationEvent) -> Any:
        self._completed.add(event.animation_id)
        return self._settle_if_terminal()

    def _child_cancel(self, event: AnimationEvent) -> Any:
        self._cancelled.add(event.animation_id)
        if self._reason is None:
            self._reason = event.reason or "child_cancelled"
        if self._stop_together:
            for child in self._children:
                if child.id != event.animation_id and not child.done:
                    child.cancel()
        return self._settle_if_terminal()

    def _settle_if_terminal(self) -> Any:
        if self._callback_delivered or not self._children:
            return None
        terminal = self._completed | self._cancelled
        if len(terminal) != len(self._children):
            return None
        self._callback_delivered = True
        if self._cancelled:
            self._status = "cancelled"
            callback = self._on_cancel
        else:
            self._status = "completed"
            callback = self._on_complete
        if callback is None:
            return None
        first = self._children[0]
        event = AnimationEvent(
            animation_id=first.id,
            status=self._status,
            node_id=first.slot.node_id,
            property=",".join(child.slot.property for child in self._children),
            reason=self._reason,
        )
        return callback(event)

    def _reject(self, reason: str) -> None:
        self._status = "rejected"
        self._reason = reason


class AnimationSequenceHandle:
    """Lifecycle handle for a composed sequence of animation plans."""

    def __init__(
        self,
        animations: Sequence["_AnimationPlan"],
        *,
        on_complete: Callable[..., Any] | None,
        on_cancel: Callable[..., Any] | None,
    ) -> None:
        self._animations = tuple(animations)
        self._on_complete = on_complete
        self._on_cancel = on_cancel
        self._index = 0
        self._current: _AnimationHandle | None = None
        self._status = "queued"
        self._reason: str | None = None
        self._first_id = 0
        self._callback_delivered = False

    @property
    def id(self) -> int:
        return self._first_id

    @property
    def status(self) -> str:
        if not self.done and self._current is not None:
            return self._current.status
        return self._status

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def slot(self) -> PresentationSlot:
        current = self._current
        if current is None:
            raise RuntimeError("Animation sequence has not started")
        return current.slot

    @property
    def done(self) -> bool:
        return self._status in {"completed", "cancelled", "rejected"}

    def cancel(self) -> bool:
        current = self._current
        if self.done or current is None:
            return False
        return current.cancel()

    def _start(self) -> None:
        self._start_current()

    def _start_current(self) -> None:
        if self._index >= len(self._animations):
            self._finish_completed(None)
            return
        try:
            current = self._animations[self._index].start(
                on_complete=self._child_complete,
                on_cancel=self._child_cancel,
            )
        except Exception:
            self._status = "rejected"
            self._reason = "sequence_start_failed"
            raise
        self._current = current
        if self._first_id == 0:
            self._first_id = current.id
        self._status = current.status

    def _child_complete(self, event: AnimationEvent) -> Any:
        self._index += 1
        if self._index < len(self._animations):
            self._start_current()
            return None
        return self._finish_completed(event)

    def _finish_completed(self, event: AnimationEvent | None) -> Any:
        self._status = "completed"
        if self._callback_delivered or self._on_complete is None:
            return None
        self._callback_delivered = True
        if event is None:
            current = self._current
            if current is None:
                return None
            event = AnimationEvent(
                animation_id=current.id,
                status="completed",
                node_id=current.slot.node_id,
                property="sequence",
            )
        return self._on_complete(event)

    def _child_cancel(self, event: AnimationEvent) -> Any:
        self._status = "cancelled"
        self._reason = event.reason or "child_cancelled"
        if self._callback_delivered or self._on_cancel is None:
            return None
        self._callback_delivered = True
        return self._on_cancel(event)


class AnimatedNode:
    """Immutable expression evaluated from one or more native drivers."""

    __slots__ = ("_expression", "_runtime", "_driver_ids", "_initial")

    def __init__(
        self,
        expression: Mapping[str, object],
        *,
        runtime: ReferenceType[Runtime],
        driver_ids: frozenset[int],
        initial: float,
    ) -> None:
        if not math.isfinite(initial):
            raise ValueError("Animated expression initial value must be finite")
        self._expression = dict(expression)
        self._runtime = runtime
        self._driver_ids = driver_ids
        self._initial = float(initial)

    @property
    def driver_ids(self) -> frozenset[int]:
        return self._driver_ids

    def to_protocol_value(self) -> dict[str, object]:
        return {
            ANIMATED_NODE_MARKER: True,
            "value": self._initial,
            "expression": self._expression,
        }

    def interpolate(
        self,
        input_range: Sequence[int | float],
        output_range: Sequence[int | float],
        *,
        extrapolate: str = "extend",
    ) -> "AnimatedNode":
        inputs = _finite_sequence(input_range, name="input_range", minimum=2)
        outputs = _finite_sequence(output_range, name="output_range", minimum=2)
        if len(inputs) != len(outputs):
            raise ValueError("input_range and output_range must have equal lengths")
        if any(right <= left for left, right in zip(inputs, inputs[1:])):
            raise ValueError("input_range must be strictly increasing")
        if extrapolate not in {"extend", "clamp", "identity"}:
            raise ValueError("extrapolate must be 'extend', 'clamp', or 'identity'")
        initial = _interpolate_number(
            self._initial,
            inputs,
            outputs,
            extrapolate=extrapolate,
        )
        return self._derive(
            {
                "op": "interpolate",
                "input": self._expression,
                "input_range": inputs,
                "output_range": outputs,
                "extrapolate": extrapolate,
            },
            initial,
        )

    def clamp(
        self,
        minimum: int | float,
        maximum: int | float,
    ) -> "AnimatedNode":
        lower = _finite_number(minimum, name="minimum")
        upper = _finite_number(maximum, name="maximum")
        if lower > upper:
            raise ValueError("minimum must be <= maximum")
        return self._derive(
            {
                "op": "clamp",
                "input": self._expression,
                "minimum": lower,
                "maximum": upper,
            },
            min(max(self._initial, lower), upper),
        )

    def _derive(self, expression: Mapping[str, object], initial: float) -> "AnimatedNode":
        return AnimatedNode(
            expression,
            runtime=self._runtime,
            driver_ids=self._driver_ids,
            initial=initial,
        )

    def _binary(self, other: object, op: str, function: Callable[[float, float], float]) -> "AnimatedNode":
        right = _coerce_animated_node(other, runtime=self._runtime)
        driver_ids = self._driver_ids | right._driver_ids
        initial = function(self._initial, right._initial)
        if not math.isfinite(initial):
            raise ValueError("Animated expression produced a non-finite value")
        return AnimatedNode(
            {"op": op, "left": self._expression, "right": right._expression},
            runtime=self._runtime,
            driver_ids=driver_ids,
            initial=initial,
        )

    def __add__(self, other: object) -> "AnimatedNode":
        return self._binary(other, "add", lambda left, right: left + right)

    def __radd__(self, other: object) -> "AnimatedNode":
        return self + other

    def __sub__(self, other: object) -> "AnimatedNode":
        return self._binary(other, "subtract", lambda left, right: left - right)

    def __rsub__(self, other: object) -> "AnimatedNode":
        return _coerce_animated_node(other, runtime=self._runtime) - self

    def __mul__(self, other: object) -> "AnimatedNode":
        return self._binary(other, "multiply", lambda left, right: left * right)

    def __rmul__(self, other: object) -> "AnimatedNode":
        return self * other

    def __truediv__(self, other: object) -> "AnimatedNode":
        def divide(left: float, right: float) -> float:
            if right == 0:
                raise ZeroDivisionError("Animated expression division by zero")
            return left / right

        return self._binary(other, "divide", divide)

    def __rtruediv__(self, other: object) -> "AnimatedNode":
        return _coerce_animated_node(other, runtime=self._runtime) / self

    def __neg__(self) -> "AnimatedNode":
        return self._derive({"op": "negate", "input": self._expression}, -self._initial)


class _AnimatedDriver(AnimatedNode):
    """Runtime-owned persistent scalar exposed by ``Animated.Value``."""

    __slots__ = ("driver_id", "_original", "_target")

    def __init__(self, runtime: Runtime, driver_id: int, initial: float) -> None:
        value = _finite_number(initial, name="Animated.Value initial")
        self.driver_id = driver_id
        self._original = value
        self._target = value
        super().__init__(
            {
                "op": "value",
                "driver_id": driver_id,
                "initial": value,
            },
            runtime=__import__("weakref").ref(runtime),
            driver_ids=frozenset({driver_id}),
            initial=value,
        )

    @property
    def target(self) -> float:
        return self._target

    def set(self, value: int | float) -> "AnimationHandle":
        return Animated.timing(self, to=value, duration=0).start()

    def reset(self) -> "AnimationHandle":
        return self.set(self._original)


class _AnimationPlan:
    """Immutable advanced animation description."""

    def start(
        self,
        *,
        on_complete: Callable[..., Any] | None = None,
        on_cancel: Callable[..., Any] | None = None,
    ) -> _AnimationHandle:
        raise NotImplementedError


@dataclass(frozen=True)
class _DriverAnimationPlan(_AnimationPlan):
    driver: _AnimatedDriver
    spec: MotionSpec
    targets: tuple[float, ...]

    def start(
        self,
        *,
        on_complete: Callable[..., Any] | None = None,
        on_cancel: Callable[..., Any] | None = None,
    ) -> AnimationHandle:
        runtime = _runtime_for_driver(self.driver)
        anchor = runtime.animated_driver_anchor(self.driver.driver_id)
        command = DriverSetTarget(
            driver_id=self.driver.driver_id,
            anchor=anchor,
            spec=self.spec,
            target=self.targets[0],
            keyframes=self.targets[1:],
        )
        handle = runtime.start_animation(
            command,
            on_complete=on_complete,
            on_cancel=on_cancel,
        )
        self.driver._target = self.targets[-1]
        return handle


@dataclass(frozen=True)
class _ParallelAnimationPlan(_AnimationPlan):
    animations: tuple[_AnimationPlan, ...]
    stop_together: bool = True

    def start(
        self,
        *,
        on_complete: Callable[..., Any] | None = None,
        on_cancel: Callable[..., Any] | None = None,
    ) -> AnimationGroupHandle:
        if not self.animations:
            raise ValueError("Animated.parallel requires at least one animation")
        from vyne.events import _wrap_handler

        group = AnimationGroupHandle(
            on_complete=(
                _wrap_handler(on_complete) if on_complete is not None else None
            ),
            on_cancel=(
                _wrap_handler(on_cancel) if on_cancel is not None else None
            ),
            stop_together=self.stop_together,
        )
        children: list[_AnimationHandle] = []
        flattened = self._flattened()
        driver_ids: set[int] = set()
        for animation in flattened:
            branch_driver_ids = _plan_driver_ids(animation)
            if driver_ids & branch_driver_ids:
                raise ValueError(
                    "Animated.parallel cannot animate the same "
                    "Animated.Value twice"
                )
            driver_ids.update(branch_driver_ids)
        try:
            for animation in flattened:
                child = animation.start(
                    on_complete=group._child_complete,
                    on_cancel=group._child_cancel,
                )
                children.append(child)
        except Exception:
            for child in children:
                child.cancel()
            group._reject("group_start_failed")
            raise
        group._attach(children)
        return group

    def _flattened(self) -> tuple[_AnimationPlan, ...]:
        result: list[_AnimationPlan] = []
        for animation in self.animations:
            if isinstance(animation, _ParallelAnimationPlan):
                result.extend(animation._flattened())
            else:
                result.append(animation)
        return tuple(result)


@dataclass(frozen=True)
class _SequenceAnimationPlan(_AnimationPlan):
    animations: tuple[_AnimationPlan, ...]

    def start(
        self,
        *,
        on_complete: Callable[..., Any] | None = None,
        on_cancel: Callable[..., Any] | None = None,
    ) -> AnimationSequenceHandle:
        from vyne.events import _wrap_handler

        handle = AnimationSequenceHandle(
            self.animations,
            on_complete=(
                _wrap_handler(on_complete) if on_complete is not None else None
            ),
            on_cancel=(
                _wrap_handler(on_cancel) if on_cancel is not None else None
            ),
        )
        handle._start()
        return handle


class Animated:
    """Advanced persistent-driver animation namespace."""

    @staticmethod
    def Value(initial: int | float) -> _AnimatedDriver:
        from vyne.state import _CURRENT_RUNTIME

        runtime = _CURRENT_RUNTIME.get()
        if runtime is None:
            raise RuntimeError(
                "Animated.Value() can only be used while rendering a component"
            )
        return runtime.use_animated_value(initial)

    @staticmethod
    def timing(
        value: _AnimatedDriver,
        *,
        to: int | float | Sequence[int | float],
        duration: int = 300,
        easing: str = "ease_out",
        retarget: str | None = None,
    ) -> _DriverAnimationPlan:
        driver = _require_driver(value)
        targets = _animation_targets(to)
        spec = Tween(
            duration_ms=duration,
            easing=easing,
            retarget=_retarget_policy(
                _resolve_retarget_policy(retarget, easing=easing)
            ),
        )
        return _DriverAnimationPlan(driver, spec, targets)

    @staticmethod
    def spring(
        value: _AnimatedDriver,
        *,
        to: int | float | Sequence[int | float],
        stiffness: float = 380.0,
        damping_ratio: float = 0.8,
        rest_value_threshold: float = 0.01,
        rest_velocity_threshold: float = 0.01,
        retarget: str | None = None,
    ) -> _DriverAnimationPlan:
        driver = _require_driver(value)
        targets = _animation_targets(to)
        spec = Spring(
            stiffness=stiffness,
            damping_ratio=damping_ratio,
            rest_value_threshold=rest_value_threshold,
            rest_velocity_threshold=rest_velocity_threshold,
            retarget=_retarget_policy(
                _resolve_retarget_policy(retarget, easing="spring")
            ),
        )
        return _DriverAnimationPlan(driver, spec, targets)

    @staticmethod
    def parallel(
        animations: Sequence[_AnimationPlan],
        *,
        stop_together: bool = True,
    ) -> _ParallelAnimationPlan:
        plans = tuple(animations)
        if not all(isinstance(plan, _AnimationPlan) for plan in plans):
            raise TypeError("Animated.parallel requires animation plans")
        return _ParallelAnimationPlan(plans, stop_together=stop_together)

    @staticmethod
    def sequence(animations: Sequence[_AnimationPlan]) -> _AnimationPlan:
        nested = tuple(animations)
        plans = tuple(
            child
            for plan in nested
            for child in (
                plan.animations
                if isinstance(plan, _SequenceAnimationPlan)
                else (plan,)
            )
        )
        if not plans:
            raise ValueError("Animated.sequence requires at least one animation")
        if not all(isinstance(plan, _AnimationPlan) for plan in plans):
            raise TypeError("Animated.sequence requires animation plans")
        first = plans[0]
        if (
            isinstance(first, _DriverAnimationPlan)
            and all(
                isinstance(plan, _DriverAnimationPlan)
                and plan.driver is first.driver
                and plan.spec == first.spec
                for plan in plans
            )
        ):
            return _DriverAnimationPlan(
                first.driver,
                first.spec,
                tuple(target for plan in plans for target in plan.targets),
            )
        return _SequenceAnimationPlan(plans)


def _plan_driver_ids(plan: _AnimationPlan) -> set[int]:
    if isinstance(plan, _DriverAnimationPlan):
        return {plan.driver.driver_id}
    if isinstance(plan, (_ParallelAnimationPlan, _SequenceAnimationPlan)):
        return {
            driver_id
            for child in plan.animations
            for driver_id in _plan_driver_ids(child)
        }
    raise TypeError(f"Unsupported animation plan: {type(plan).__name__}")


def _runtime_for_driver(driver: _AnimatedDriver) -> Runtime:
    runtime = driver._runtime()
    if runtime is None:
        raise RuntimeError("Animated.Value belongs to a released Runtime")
    from vyne.state import _CURRENT_RUNTIME

    if _CURRENT_RUNTIME.get() is not runtime:
        raise RuntimeError(
            "Animated animation must start in its owning Runtime's event context"
        )
    return runtime


def _require_driver(value: object) -> _AnimatedDriver:
    if not isinstance(value, _AnimatedDriver):
        raise TypeError("Animated.timing/spring require an Animated.Value")
    return value


def _finite_number(value: object, *, name: str) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise TypeError(f"{name} must be a finite number")
    return float(value)


def _finite_sequence(
    values: Sequence[int | float],
    *,
    name: str,
    minimum: int,
) -> list[float]:
    if isinstance(values, str | bytes | bytearray):
        raise TypeError(f"{name} must be a numeric sequence")
    result = [
        _finite_number(value, name=f"{name}[{index}]")
        for index, value in enumerate(values)
    ]
    if len(result) < minimum:
        raise ValueError(f"{name} must contain at least {minimum} values")
    return result


def _animation_targets(value: object) -> tuple[float, ...]:
    if isinstance(value, Sequence) and not isinstance(
        value, str | bytes | bytearray
    ):
        if len(value) == 0:
            raise ValueError("Animation keyframes must not be empty")
        return tuple(_finite_sequence(value, name="to", minimum=1))
    return (_finite_number(value, name="to"),)


def _coerce_animated_node(
    value: object,
    *,
    runtime: ReferenceType[Runtime],
) -> AnimatedNode:
    if isinstance(value, AnimatedNode):
        if value._runtime() is not runtime():
            raise ValueError("Animated expressions cannot cross Runtime instances")
        return value
    number = _finite_number(value, name="Animated expression operand")
    return AnimatedNode(
        {"op": "constant", "value": number},
        runtime=runtime,
        driver_ids=frozenset(),
        initial=number,
    )


def _interpolate_number(
    value: float,
    inputs: Sequence[float],
    outputs: Sequence[float],
    *,
    extrapolate: str,
) -> float:
    if value < inputs[0]:
        if extrapolate == "identity":
            return value
        if extrapolate == "clamp":
            return outputs[0]
        index = 0
    elif value > inputs[-1]:
        if extrapolate == "identity":
            return value
        if extrapolate == "clamp":
            return outputs[-1]
        index = len(inputs) - 2
    else:
        index = next(
            (
                candidate
                for candidate in range(len(inputs) - 1)
                if inputs[candidate] <= value <= inputs[candidate + 1]
            ),
            len(inputs) - 2,
        )
    input_start = inputs[index]
    input_end = inputs[index + 1]
    fraction = (value - input_start) / (input_end - input_start)
    return outputs[index] + (outputs[index + 1] - outputs[index]) * fraction


def encode_animated_values(value: object) -> object:
    """Recursively lower AnimatedNode instances to protocol-safe markers.

    Each AnimatedNode is encoded with its stable operation identity
    so the Kotlin engine can locate and animate the target field.

    Accepts dict and Mapping (e.g. FrozenMap) so deeply frozen props
    are lowered correctly for the wire (MODEL-03).
    """
    from collections.abc import Mapping
    if isinstance(value, AnimatedNode):
        return value.to_protocol_value()
    if isinstance(value, list | tuple):
        return [encode_animated_values(item) for item in value]
    if isinstance(value, (dict, Mapping)):
        return {key: encode_animated_values(item) for key, item in value.items()}
    return value


def is_animated_node_payload(value: object) -> bool:
    """Return True if ``value`` is a protocol marker for an animated node.

    Accepts dict and Mapping (e.g. FrozenMap) so that deeply frozen
    element props still pass the animated-node check (MODEL-03).
    """
    from collections.abc import Mapping
    return isinstance(value, (dict, Mapping)) and (
        value.get(ANIMATED_NODE_MARKER) is True
    )


def animated_driver_ids(value: object) -> frozenset[int]:
    """Return every persistent driver referenced by an encoded value."""
    if not isinstance(value, Mapping):
        return frozenset()
    if value.get(ANIMATED_NODE_MARKER) is not True:
        return frozenset()
    expression = value.get("expression")
    result: set[int] = set()

    def visit(node: object) -> None:
        if not isinstance(node, Mapping):
            return
        if node.get("op") == "value":
            driver_id = node.get("driver_id")
            if type(driver_id) is int and driver_id > 0:
                result.add(driver_id)
        for child_name in ("input", "left", "right"):
            visit(node.get(child_name))

    visit(expression)
    return frozenset(result)


def _resolve_retarget_policy(value: object, *, easing: str) -> str:
    if value is None:
        return "maintain_velocity" if easing == "spring" else "restart"
    if not isinstance(value, str) or value not in _RETARGET_POLICIES:
        raise ValueError(
            "Animation retarget must be one of "
            f"{sorted(_RETARGET_POLICIES)}, got {value!r}"
        )
    return value


def _retarget_policy(value: object) -> RetargetPolicy:
    # animate() resolves its optional public argument before constructing a
    # MotionSpec.
    return RetargetPolicy[str(value).upper()]


_UNSET = object()
_DIRECT_PROPERTY_ALIASES = {
    "x": "translation_x",
    "y": "translation_y",
    "alpha": "opacity",
}


def animate(
    target: "int | Ref | ViewHandle",
    prop: str | None = None,
    *,
    from_: float | Mapping[str, float] | None = None,
    to: float | Sequence[float] | object = _UNSET,
    duration: int = 300,
    easing: str = "ease_out",
    damping_ratio: float | None = None,
    stiffness: float | None = None,
    retarget: str | None = None,
    on_complete: Callable[..., Any] | None = None,
    on_cancel: Callable[..., Any] | None = None,
    **properties: float | Sequence[float],
) -> AnimationHandle | AnimationGroupHandle:
    """Immediately animate one or more properties on a mounted view.

    *target* may be a raw view ID (``int``), a :class:`Ref`, or a
    :class:`ViewHandle`.  Passing an ``Element`` is no longer supported
    — use ``Ref`` for per-mount identity.

    The preferred form names destinations directly::

        animate(event.target, x=80, y=-8, scale=[0.96, 1.0])

    ``x``/``y`` are presentation translations and ``scale`` expands to both
    axes.  The legacy ``animate(target, "opacity", to=...)`` form remains
    supported.  Omitted starting values are read from the live native
    presentation, making interruption and reversal continuous.
    """
    from vyne.state import _CURRENT_RUNTIME
    from vyne.refs import Ref, ViewHandle

    runtime = _CURRENT_RUNTIME.get()
    if runtime is None:
        raise RuntimeError(
            "animate() can only be used while rendering or in event handlers"
        )

    if isinstance(target, int):
        view_id = target
    elif isinstance(target, ViewHandle):
        if not target.valid:
            raise RuntimeError(
                "ViewHandle is stale — the target view has been removed or replaced"
            )
        view_id = target.node_id
    elif isinstance(target, Ref):
        handle = target.current
        if handle is None:
            raise RuntimeError(
                "Ref is not attached to any view — did you call animate() "
                "before the element was rendered?"
            )
        if not handle.valid:
            raise RuntimeError(
                "Ref handle is stale — the target view has been removed or replaced"
            )
        view_id = handle.node_id
    else:
        raise TypeError(
            f"animate() target must be int, Ref, or ViewHandle, "
            f"got {type(target).__name__}"
        )

    if on_complete is not None and not callable(on_complete):
        raise TypeError("on_complete must be callable or None")
    if on_cancel is not None and not callable(on_cancel):
        raise TypeError("on_cancel must be callable or None")

    resolved_retarget = _resolve_retarget_policy(retarget, easing=easing)
    if easing == "spring":
        spec: MotionSpec = Spring(
            damping_ratio=0.8 if damping_ratio is None else damping_ratio,
            stiffness=380.0 if stiffness is None else stiffness,
            retarget=_retarget_policy(resolved_retarget),
        )
    else:
        if damping_ratio is not None or stiffness is not None:
            raise ValueError(
                "damping_ratio and stiffness require easing='spring'"
            )
        spec = Tween(
            duration_ms=duration,
            easing=easing,
            retarget=_retarget_policy(resolved_retarget),
        )

    destinations: dict[str, object] = {}
    if prop is not None:
        if not isinstance(prop, str) or not prop.strip():
            raise ValueError("Animation property must be a non-empty string")
        if properties:
            raise TypeError(
                "Legacy positional property form cannot be mixed with named destinations"
            )
        canonical = _PROPERTY_ALIASES.get(prop, prop)
        destinations[canonical] = 1.0 if to is _UNSET else to
    else:
        if to is not _UNSET:
            raise TypeError("'to' requires the legacy positional property form")
        destinations.update(properties)

    if not destinations:
        raise ValueError("animate() requires at least one property destination")

    scale = destinations.pop("scale", _UNSET)
    if scale is not _UNSET:
        if "scale_x" in destinations or "scale_y" in destinations:
            raise ValueError("scale cannot be combined with scale_x or scale_y")
        destinations["scale_x"] = scale
        destinations["scale_y"] = scale

    canonical_destinations: dict[str, object] = {}
    for name, destination in destinations.items():
        canonical = _DIRECT_PROPERTY_ALIASES.get(
            name,
            _PROPERTY_ALIASES.get(name, name),
        )
        if canonical in canonical_destinations:
            raise ValueError(f"Duplicate animation destination for {canonical!r}")
        if canonical not in ANIMATABLE_VIEW_PROPERTIES:
            raise ValueError(f"Property {name!r} is not animatable")
        canonical_destinations[canonical] = destination

    def source_for(name: str) -> float | None:
        if from_ is None:
            return None
        if isinstance(from_, Mapping):
            candidates = [name]
            if name == "translation_x":
                candidates.append("x")
            elif name == "translation_y":
                candidates.append("y")
            elif name in {"scale_x", "scale_y"}:
                candidates.append("scale")
            for candidate in candidates:
                if candidate in from_:
                    return _finite_number(
                        from_[candidate],
                        name=f"from_[{candidate!r}]",
                    )
            return None
        return _finite_number(from_, name="from_")

    commands: list[SetTarget] = []
    from vyne.extensions_registry import resolve_prop

    for name, destination in canonical_destinations.items():
        targets = _animation_targets(destination)
        command = SetTarget(
            slot=PresentationSlot(node_id=view_id, property=name),
            spec=spec,
            target=targets[0],
            keyframes=targets[1:],
            from_value=source_for(name),
        )
        for index, target_value in enumerate(command.targets):
            resolve_prop(name).value.validate(
                target_value,
                path=f"animation.{name}.targets[{index}]",
            )
        if command.from_value is not None:
            resolve_prop(name).value.validate(
                command.from_value,
                path=f"animation.{name}.from_value",
            )
        commands.append(command)

    return _start_commands(
        runtime,
        commands,
        on_complete=on_complete,
        on_cancel=on_cancel,
    )


def _start_commands(
    runtime: Runtime,
    commands: Sequence[SetTarget | DriverSetTarget],
    *,
    on_complete: Callable[..., Any] | None,
    on_cancel: Callable[..., Any] | None,
) -> AnimationHandle | AnimationGroupHandle:
    if len(commands) == 1:
        return runtime.start_animation(
            commands[0],
            on_complete=on_complete,
            on_cancel=on_cancel,
        )

    from vyne.events import _wrap_handler

    group = AnimationGroupHandle(
        on_complete=(
            _wrap_handler(on_complete) if on_complete is not None else None
        ),
        on_cancel=(
            _wrap_handler(on_cancel) if on_cancel is not None else None
        ),
    )
    children: list[AnimationHandle] = []
    try:
        for command in commands:
            children.append(
                runtime.start_animation(
                    command,
                    on_complete=group._child_complete,
                    on_cancel=group._child_cancel,
                )
            )
    except Exception:
        for child in children:
            child.cancel()
        group._reject("group_start_failed")
        raise
    group._attach(children)
    return group
