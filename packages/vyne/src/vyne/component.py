"""Stateful component scopes with subtree-local invalidation.

The :func:`component` decorator creates an explicit render boundary.  Calls
made while a Runtime is rendering are owned by the current component scope;
state allocated by the decorated function invalidates only that scope.

Outside a Runtime render the wrapper remains transparent, which keeps
stateless components convenient to construct and test directly.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast, overload

from vyne.elements import Element
from vyne.state import current_runtime
from vyne.values import validate_canonical_key

P = ParamSpec("P")
R = TypeVar("R", bound=Element)


@overload
def component(function: Callable[P, R], /) -> Callable[P, R]: ...


@overload
def component(
    function: None = None,
    /,
    *,
    key: Callable[P, Any] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def component(
    function: Callable[P, R] | None = None,
    /,
    *,
    key: Callable[P, Any] | None = None,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Give a component isolated hooks and subtree-local invalidation.

    The decorated function must return one :class:`~vyne.elements.Element`.
    Unkeyed calls are matched by order within the owning component, using the
    same stable-order rule as ``state()`` hooks.

    ``key`` may be a callable receiving the same arguments as the component.
    Its result gives each call stable identity across sibling reordering::

        @component(key=lambda item: item.id)
        def Item(item):
            ...

    A keyed component's returned root Element receives the same key when it
    does not already have one. An explicitly returned, different root key is
    rejected so component state and native identity cannot diverge.
    """
    if key is not None and not callable(key):
        raise TypeError("component key must be callable")

    def decorate(actual: Callable[P, R]) -> Callable[P, R]:
        if not callable(actual):
            raise TypeError("component() requires a callable")

        @wraps(actual)
        def scoped(*args: P.args, **kwargs: P.kwargs) -> R:
            runtime = current_runtime()
            if runtime is None:
                return actual(*args, **kwargs)
            component_key = None
            if key is not None:
                component_key = key(*args, **kwargs)
                if component_key is None:
                    raise TypeError("component key callable must not return None")
                validate_canonical_key(component_key, path="Component key")
            return cast(
                R,
                runtime.render_component(
                    actual,
                    args,
                    kwargs,
                    component_key=component_key,
                    keyed=key is not None,
                ),
            )

        # Runtime unwraps a decorated root component so it owns the root scope
        # directly instead of creating a redundant child scope.
        setattr(scoped, "__vyne_component_function__", actual)
        setattr(scoped, "__vyne_component_key_function__", key)
        return scoped

    if function is None:
        return decorate
    return decorate(function)
