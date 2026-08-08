"""The root app context: host capabilities delivered to the app function.

The app entry point receives one ``AppContext`` argument holding the launch
data and every host capability (app state, and later back handling,
dimensions, keyboard, ...). The runtime owns the capability objects; this
module only defines their public surface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class AppState:
    """The app's foreground/background lifecycle.

    ``current`` is the last known state: ``"active"``, ``"inactive"``, or
    ``"background"``. ``on_change`` registers a handler that fires
    immediately with the current state and then on every transition; the
    returned callable disposes the subscription.
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    @property
    def current(self) -> str:
        return self._runtime.current_app_state

    def on_change(
        self,
        handler: Callable[[str], Any],
    ) -> Callable[[], None]:
        return self._runtime.subscribe_app_state(handler)


class BackHandler:
    """Android system back-press interception.

    ``addEventListener`` registers a handler that runs when the user
    presses the system back button; the returned callable disposes the
    registration. Handlers run in LIFO order (last registered first).
    The first handler that returns ``True`` consumes the press; if none
    does, the host performs its default (the activity finishes).
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def addEventListener(
        self,
        handler: Callable[[], Any],
    ) -> Callable[[], None]:
        return self._runtime.add_back_handler(handler)


@dataclass(frozen=True)
class AppContext:
    """Everything the host hands the app root on each render.

    ``launch`` changes on every Android launch; capability wrappers are
    recreated per delivery but their state lives on the runtime, so
    registrations and subscriptions survive across launches.
    """

    launch: Any
    app_state: AppState
    back_handler: BackHandler


__all__ = ["AppContext", "AppState", "BackHandler"]
