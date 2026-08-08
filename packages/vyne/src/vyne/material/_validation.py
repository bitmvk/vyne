"""Shared validators and canonical value enforcement for Material components.

Python owns all policy: validation, defaults, finite/range/dimension/color
checks, disabled precedence, and interaction-state resolution.  This module
provides the central functions consumed by every Material component so that
rules are shared, not scattered.
"""

from __future__ import annotations

import math
from typing import Any, TYPE_CHECKING

from vyne.material.theme import ColorScheme

if TYPE_CHECKING:
    from vyne.material._callbacks import CallbackAdapter


def validate_finite(value: Any, name: str) -> float:
    """Reject bool, None, NaN, inf, and non-real; return a plain float."""
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number, not bool")
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    if value is None:
        raise TypeError(f"{name} must be a number, got None")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be convertible to float") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


def validate_step(step: Any) -> float | None:
    """``None`` is a valid absent step; otherwise positive finite."""
    if step is None:
        return None
    result = validate_finite(step, "step")
    if result <= 0:
        raise ValueError(f"step must be greater than zero, got {result}")
    return result


def alpha(color: str, opacity: float) -> str:
    """Return a canonical ``#RRGGBBAA`` color string with applied opacity.

    ``color`` may be ``#RRGGBB`` or ``#RRGGBBAA``; the original alpha is
    discarded and replaced by ``opacity`` (0.0–1.0).  The result is in
    canonical RGBA wire format.  Kotlin's ``parseColorString`` swizzles
    the alpha byte to the front for Android's ARGB native representation.
    """
    normalized = color.lstrip("#")
    if len(normalized) == 8:
        normalized = normalized[:6]
    if len(normalized) != 6:
        raise ValueError("color must be #RRGGBB or #RRGGBBAA")
    channel = round(max(0.0, min(1.0, float(opacity))) * 255)
    return f"#{normalized.upper()}{channel:02X}"


def resolve_ripple_color(
    colors: ColorScheme,
    *,
    enabled: bool,
    foreground: str,
    selected: bool = False,
) -> str:
    """Central ripple-color derivation from the resolved foreground.

    Returns canonical RGBA (``#RRGGBBAA``).  When disabled the ripple
    is fully transparent so no ripple is visible.
    """
    if not enabled:
        return "#00000000"  # fully transparent — no visible ripple
    return alpha(foreground, 0.12)


# ---------------------------------------------------------------------------
# Slider model (MATERIAL-01)
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass(frozen=True)
class SliderSpec:
    """Immutable validated specification for a Slider or RangeSlider.

    Enforces finite bounds, positive step, and usable width (>20dp so that
    the 10dp endpoint insets on each side leave at least 1dp of track).
    """

    minimum: float
    maximum: float
    step: float | None
    width: float

    def __post_init__(self) -> None:
        lo = validate_finite(self.minimum, "minimum")
        hi = validate_finite(self.maximum, "maximum")
        if hi <= lo:
            raise ValueError(
                f"maximum must be greater than minimum (got {lo}, {hi})"
            )
        object.__setattr__(self, "minimum", lo)
        object.__setattr__(self, "maximum", hi)

        st = validate_step(self.step)
        object.__setattr__(self, "step", st)

        w = validate_finite(self.width, "width")
        if w <= 20:
            raise ValueError(
                f"width must be greater than 20 dp "
                f"(required for 10 dp endpoint insets on each side), got {w}"
            )
        object.__setattr__(self, "width", w)

    @property
    def usable_width(self) -> float:
        """Track width after subtracting the 10dp inset on each side."""
        return self.width - 20.0

    @property
    def is_discrete(self) -> bool:
        return self.step is not None

    def normalize(self, raw: float) -> float:
        """Snap *raw* to nearest legal step value and clamp to [min, max]."""
        return _normalize_step_value(raw, self.minimum, self.maximum, self.step)

    def value_at(self, x: float) -> float:
        """Resolve a local pointer coordinate to a legal value."""
        inset = 10.0
        usable = max(1.0, self.usable_width)
        fraction = max(0.0, min(1.0, (x - inset) / usable))
        if fraction <= 0:
            return self.minimum
        if fraction >= 1:
            return self.maximum
        raw = self.minimum + (self.maximum - self.minimum) * fraction
        return _normalize_step_value(raw, self.minimum, self.maximum, self.step)

    @staticmethod
    def validate_range_slider_values(
        values: object,
        spec: "SliderSpec",
    ) -> tuple[float, float]:
        """Validate one already ordered RangeSlider controlled pair."""
        if not isinstance(values, tuple) or len(values) != 2:
            raise TypeError(
                "RangeSlider values must be a tuple of exactly two numbers"
            )
        v0 = validate_finite(values[0], "values[0]")
        v1 = validate_finite(values[1], "values[1]")
        if v0 < spec.minimum or v0 > spec.maximum:
            raise ValueError(
                f"values[0]={v0} is outside [{spec.minimum}, {spec.maximum}]"
            )
        if v1 < spec.minimum or v1 > spec.maximum:
            raise ValueError(
                f"values[1]={v1} is outside [{spec.minimum}, {spec.maximum}]"
            )
        if v0 > v1:
            raise ValueError("RangeSlider values must be ordered start <= end")
        start = _normalize_step_value(v0, spec.minimum, spec.maximum, spec.step)
        end = _normalize_step_value(v1, spec.minimum, spec.maximum, spec.step)
        if start > end:
            raise ValueError("RangeSlider snapped values must remain ordered")
        return start, end


# ---------------------------------------------------------------------------
# Mount-local gesture state (MATERIAL-01)
# ---------------------------------------------------------------------------


class SliderGesture:
    """Per-mount gesture state owned by Python, not by Kotlin.

    Each mounted slider/render node gets one instance keyed by
    ``(node_id, gesture_id)``.  The Runtime/composition layer manages
    the lifecycle; closures stored on Element props are stateless
    stubs that delegate here.

    Lifecycle:
    * ``down(x)`` — initialises the gesture with *active_thumb*.
    * ``move(x)`` — emits only when the normalised value changes.
    * ``up()`` / ``cancel()`` — resets the gesture so a fresh down starts
      a new gesture.
    """

    __slots__ = (
        "_adapter",
        "_active_thumb",
        "_last_emitted",
        "_phase",
        "_spec",
        "_callback",
    )

    def __init__(
        self,
        spec: SliderSpec,
        adapter: "CallbackAdapter | None",
    ) -> None:
        self._spec = spec
        self._adapter = adapter
        self._active_thumb: str = ""
        self._last_emitted: float | None = None
        self._phase: str = "idle"  # idle | active

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def active_thumb(self) -> str:
        return self._active_thumb

    def down(self, thumb: str, x: float) -> None:
        """Begin a gesture on *thumb* ("start" or "end")."""
        self._active_thumb = thumb
        self._phase = "active"
        self._last_emitted = None
        target = self._spec.value_at(x)
        self._maybe_emit(target)

    def move(self, x: float) -> None:
        """Drag update — emit only when the normalised value changed."""
        if self._phase != "active":
            return
        target = self._spec.value_at(x)
        self._maybe_emit(target)

    def up(self) -> None:
        """End the gesture normally."""
        self._phase = "idle"
        self._active_thumb = ""
        self._last_emitted = None

    def cancel(self) -> None:
        """Cancel the gesture (e.g. parent scroll intercept)."""
        self.up()

    def tap(self, x: float) -> None:
        """A discrete tap — always emits once regardless of last value."""
        target = self._spec.value_at(x)
        if self._adapter is not None:
            self._adapter.invoke(target)

    def _maybe_emit(self, target: float) -> None:
        if self._adapter is None:
            return
        if self._last_emitted is not None and math.isclose(
            target, self._last_emitted, rel_tol=1e-9, abs_tol=1e-9
        ):
            return
        self._last_emitted = target
        self._adapter.invoke(target)


class RangeSliderGesture:
    """Dual-thumb gesture state for RangeSlider.

    Manages two :class:`SliderGesture` instances (one per thumb) and
    emits complete ``(start, end)`` tuples through the shared adapter.
    """

    __slots__ = ("_adapter", "_spec", "_start_gesture", "_end_gesture",
                 "_start", "_end")

    def __init__(
        self,
        spec: SliderSpec,
        adapter: "CallbackAdapter | None",
        initial_start: float,
        initial_end: float,
    ) -> None:
        self._spec = spec
        self._adapter = adapter
        self._start = initial_start
        self._end = initial_end
        self._start_gesture = SliderGesture(spec, None)
        self._end_gesture = SliderGesture(spec, None)

    @property
    def start(self) -> float:
        return self._start

    @property
    def end(self) -> float:
        return self._end

    def down_start(self, x: float) -> None:
        self._start_gesture.down("start", x)
        target = min(self._spec.value_at(x), self._end)
        if not math.isclose(target, self._start, rel_tol=1e-9, abs_tol=1e-9):
            self._start = target
            self._emit()

    def move_start(self, x: float) -> None:
        if self._start_gesture.phase != "active":
            return
        target = min(self._spec.value_at(x), self._end)
        if not math.isclose(target, self._start, rel_tol=1e-9, abs_tol=1e-9):
            self._start = target
            self._emit()

    def up_start(self) -> None:
        self._start_gesture.up()

    def cancel_start(self) -> None:
        self._start_gesture.cancel()

    def down_end(self, x: float) -> None:
        self._end_gesture.down("end", x)
        target = max(self._spec.value_at(x), self._start)
        if not math.isclose(target, self._end, rel_tol=1e-9, abs_tol=1e-9):
            self._end = target
            self._emit()

    def move_end(self, x: float) -> None:
        if self._end_gesture.phase != "active":
            return
        target = max(self._spec.value_at(x), self._start)
        if not math.isclose(target, self._end, rel_tol=1e-9, abs_tol=1e-9):
            self._end = target
            self._emit()

    def up_end(self) -> None:
        self._end_gesture.up()

    def cancel_end(self) -> None:
        self._end_gesture.cancel()

    def _emit(self) -> None:
        if self._adapter is not None:
            self._adapter.invoke((self._start, self._end))


# ---------------------------------------------------------------------------
# Slider tick / target helpers
# ---------------------------------------------------------------------------


def _normalize_step_value(
    raw: float,
    minimum: float,
    maximum: float,
    step: float | None,
) -> float:
    """Snap *raw* to the nearest legal step value.

    When ``step`` is ``None`` the raw continuous value is returned unmodified.
    """
    if step is None:
        return float(max(minimum, min(maximum, raw)))
    ticks = math.floor((raw - minimum) / step + 0.5)
    return float(max(minimum, min(maximum, minimum + ticks * step)))


def slider_targets(spec: SliderSpec) -> list[float]:
    """Return stable tick values for discrete sliders (both ends included).

    When *spec.step* is ``None`` (continuous), return an empty list —
    continuous sliders must not build unused target lists.
    """
    if spec.step is None:
        return []  # continuous: no discrete targets
    minimum, maximum, step = spec.minimum, spec.maximum, spec.step
    span = maximum - minimum
    divisions = math.floor(span / step + 1e-9)
    if divisions > 100:
        sampled: list[float] = []
        for index in range(101):
            raw = minimum + span * index / 100
            snapped = _normalize_step_value(raw, minimum, maximum, step)
            if not sampled or not math.isclose(sampled[-1], snapped):
                sampled.append(snapped)
        if not math.isclose(sampled[-1], maximum):
            sampled.append(maximum)
        else:
            sampled[-1] = maximum
        return sampled
    targets = [minimum + step * index for index in range(divisions + 1)]
    if not math.isclose(targets[-1], maximum, rel_tol=1e-9, abs_tol=1e-9):
        targets.append(maximum)
    else:
        targets[-1] = maximum
    return targets
