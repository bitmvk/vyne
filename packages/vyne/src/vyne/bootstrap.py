"""Attempt-scoped framework bootstrap for user application modules."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from importlib import import_module, reload
from inspect import Parameter, signature
import inspect
import sys
import threading
from types import ModuleType
from typing import Any

from vyne.context import AppContext
from vyne.launch import LaunchData
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport, Transport


@dataclass
class _RegistrationAttempt:
    target_module: str
    records: list[tuple[str, Callable[..., Any]]] = field(default_factory=list)
    # The app's pre_launch hook (latest run_app registration; reload creates
    # a fresh object each attempt, so it is attempt-owned, never global).
    app_hook: Callable[[AppContext], None] | None = None


_registration_attempt: ContextVar[_RegistrationAttempt | None] = ContextVar(
    "vyne_registration_attempt", default=None
)
_start_lock = threading.Lock()

# No persistent pre_launch state exists: the hook is the app's own, set
# via run_app(pre_launch=...) per attempt. Extensions export plain launch
# functions and the APP composes them into its hook — ordering and
# side-effect policy belong to the application (tools, not finished things).


def run_app(
    main: Callable[..., Any],
    *,
    pre_launch: Callable[[AppContext], None] | None = None,
) -> None:
    """Register one app only while its host import attempt is active.

    *pre_launch* is the app's capture hook: called with every ``AppContext``
    (cold and warm) before the render pass. It runs outside the render pass,
    so it MUST NOT call ``state()``; errors are logged and never block the
    launch. The app's hook runs before extension hooks.
    """
    if not callable(main):
        raise TypeError("run_app() expects a callable app entry point")
    defining_module = getattr(main, "__module__", None)
    if not isinstance(defining_module, str):
        raise TypeError(
            "run_app() could not determine the defining module; "
            "pass a function defined at module level"
        )
    attempt = _registration_attempt.get()
    if attempt is None:
        raise RuntimeError(
            "run_app() was called outside a host start sequence. "
            "Start the module through the Vyne host bootstrap."
        )
    if pre_launch is not None:
        if not callable(pre_launch):
            raise TypeError("run_app() pre_launch must be a callable")
        if inspect.iscoroutinefunction(pre_launch):
            raise TypeError("pre_launch must be synchronous in v1 (async hooks are not supported)")
        _accepts_context(pre_launch)  # zero args or exactly one AppContext
    # Attempt-owned: the latest registration wins — including "no hook".
    attempt.app_hook = pre_launch
    attempt.records.append((defining_module, main))


def _start_registered_app(
    module_name: str = "app",
    *,
    transport: Transport | None = None,
    launch_data: LaunchData | None = None,
    root_name: str = "App",
    session_id: str | None = None,
) -> Runtime:
    """Import one module and resolve exactly its attempt-local registration."""
    del root_name  # registration is the sole startup authority
    if not _start_lock.acquire(blocking=False):
        raise RuntimeError("Another app start attempt is already in progress")

    attempt = _RegistrationAttempt(module_name)
    token = _registration_attempt.set(attempt)
    try:
        if module_name in sys.modules:
            cached = sys.modules[module_name]
            if getattr(cached, "__spec__", None) is None:
                # A cached/faux module did not execute inside this attempt and
                # therefore contributes zero registrations.
                module = cached
            else:
                module = reload(cached)
        else:
            module = import_module(module_name)
        root = _resolve_registration(module, module_name, attempt.records)
        accepts_context = _accepts_context(root)
        initial_launch = launch_data if launch_data is not None else LaunchData()
        if not isinstance(initial_launch, LaunchData):
            raise TypeError("launch_data must be a LaunchData instance")
        # Capture hook: the app's pre_launch runs before the first render.
        # It receives the AppContext so it can read the launch and the
        # app_state. Errors are logged and never block the launch. The hook
        # travels WITH the Runtime so warm deliveries read exactly what the
        # cold start used — no cross-module copies.
        chain = (attempt.app_hook,) if attempt.app_hook is not None else ()
        runtime = Runtime(
            root,
            root_args=(),
            transport=transport or MemoryTransport(),
            pre_launch_hooks=chain,
            session_id=session_id,
        )
        if chain:
            _run_pre_launch_chain(chain, runtime.build_root_context(initial_launch))
        if accepts_context:
            runtime.set_context_root(initial_launch)
        runtime.mount()
        return runtime
    finally:
        attempt.records.clear()
        _registration_attempt.reset(token)
        _start_lock.release()


def _run_pre_launch_chain(
    chain: list[Callable[[AppContext], None]]
    | tuple[Callable[[AppContext], None], ...],
    context: AppContext,
) -> None:
    """Run every pre_launch hook; errors are logged and never block."""
    import inspect
    import logging

    logger = logging.getLogger("vyne")
    for fn in chain:
        try:
            if _accepts_context(fn):
                result = fn(context)
            else:
                result = fn()  # zero-arg hook: ignores the launch entirely
        except Exception as exc:  # noqa: BLE001 - hooks must never block
            logger.error("pre_launch hook %r failed: %s", fn, exc)
            continue
        if inspect.isawaitable(result):
            result.close()  # never leak an unawaited coroutine
            logger.error(
                "pre_launch hook %r returned a coroutine; async hooks are "
                "not supported in v1 (sync only)",
                fn,
            )


def _resolve_registration(
    module: ModuleType,
    module_name: str,
    records: list[tuple[str, Callable[..., Any]]],
) -> Callable[..., Any]:
    """Reject zero, duplicate, foreign, and mixed registrations exactly."""
    target_names = {module_name, module.__name__}
    foreign = [(name, app) for name, app in records if name not in target_names]
    own = [(name, app) for name, app in records if name in target_names]
    if foreign:
        modules = sorted({name for name, _ in foreign})
        raise RuntimeError(
            f"Foreign run_app() registration(s) from {modules!r} during "
            f"startup of {module_name!r}"
        )
    if not own:
        raise RuntimeError(
            f"Module {module_name!r} made no run_app() registration during "
            "the active host import attempt"
        )
    if len(own) != 1:
        raise RuntimeError(
            f"Module {module_name!r} made {len(own)} run_app() registrations; "
            "exactly one is required"
        )
    return own[0][1]


def _accepts_context(main: Callable[..., Any]) -> bool:
    """Return whether an app takes the AppContext argument, rejecting
    ambiguous signatures.

    The app entry point may take no arguments, or exactly one positional
    argument: the ``AppContext`` holding the launch and host capabilities.
    """
    try:
        parameters = list(signature(main).parameters.values())
    except (TypeError, ValueError) as exc:
        raise TypeError(
            "run_app() entry point must expose an inspectable signature"
        ) from exc

    if not parameters:
        return False
    if (
        len(parameters) == 1
        and parameters[0].kind
        in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    ):
        return True
    raise TypeError(
        "run_app() entry point must accept either no arguments or exactly "
        "one positional AppContext argument"
    )
