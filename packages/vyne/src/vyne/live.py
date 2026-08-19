"""Dev-only hot reload: swap the running app's Python without a rebuild.

Live mode is a host capability, not an app feature: the app under
development is a normal host APK, and ``vyne live push`` deploys the app's
own Python sources (plus extension python) to ``<filesDir>/vyne-live`` on
the device, then bumps a ``REV`` marker.

``install()`` runs at the top of ``start_direct``, before the app module is
imported. When the ``ENABLED`` marker is present it:

1. puts ``<filesDir>/vyne-live`` at the front of ``sys.path`` so ``import
   app`` (and its submodules) resolve to the pushed copies instead of the
   frozen APK ones — evicting previously-imported swappable modules from
   ``sys.modules`` so re-import is a true re-read;
2. starts a watcher thread that, on ``REV`` change, asks the host Activity
   to recreate itself (``MainActivity.requestReload()``). The recreating
   Activity cold-starts a new Python session that mounts the new code.

Only the app's own Python and extension python are swappable; the framework
and the Kotlin/native layer are frozen in the APK and still need a rebuild.

Live mode never has effect unless ``ENABLED`` exists, so normal debug and
release builds behave exactly as before. All failures here are swallowed:
an unusable live dir must never block app startup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

logger = logging.getLogger("vyne.live")

_DIR_NAME = "vyne-live"
_ENABLED_MARKER = "ENABLED"
_REV_FILE = "REV"


def _live_dir(activity: Any) -> Path | None:
    """Resolve ``<filesDir>/vyne-live`` for the host Activity, if reachable."""
    try:
        files_dir = activity.getFilesDir().getAbsolutePath()
        if not files_dir:
            return None
        return Path(files_dir) / _DIR_NAME
    except Exception:  # pragma: no cover - host interaction is best-effort
        logger.debug("live: could not resolve files dir", exc_info=True)
        return None


def _enabled(live_dir: Path) -> bool:
    return (live_dir / _ENABLED_MARKER).is_file()


def evict_swappable(
    module_name: str,
    live_dir: Path,
    sys_modules: dict[str, Any] | None = None,
) -> None:
    """Drop cached modules that must be re-read from the live tree.

    *module_name* (the app entry) is always evicted so the next import finds
    the pushed copy on ``sys.path[0]``. Any module whose ``__file__`` lives
    under the live tree is also dropped — those are the app's own submodules
    and extension modules copied in by a previous live session. Modules
    imported from the frozen APK on the very first (pre-live) session are
    not dropped here; that transition is handled by a cold restart (see the
    CLI), so their stale copies never survive into a live session.
    """
    modules = sys.modules if sys_modules is None else sys_modules
    live = os.path.abspath(os.path.realpath(str(live_dir)))
    drop = {module_name}
    for name, module in list(modules.items()):
        path = getattr(module, "__file__", None)
        if path and os.path.abspath(os.path.realpath(path)).startswith(
            live + os.sep
        ):
            drop.add(name)
    for name in drop:
        modules.pop(name, None)


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------

# One process-wide watcher: multiple installs (activity recreates within a
# session) re-arm it, they never stack threads. The host is re-bound on
# every install so the watcher always targets the current Activity — a
# recreated Activity hands over a new DirectRenderHost, and a stale closes
# over a destroyed one that silently swallows reloads.
_watcher_lock = threading.Lock()
_watcher: threading.Thread | None = None
_watcher_host: Any = None
_watcher_stop = threading.Event()
_reload_pending = threading.Event()


def _start_watcher(host: Any, live_dir: Path, poll_interval_s: float) -> None:
    global _watcher, _watcher_host
    _watcher_host = host
    with _watcher_lock:
        if _watcher is not None and _watcher.is_alive():
            return
        _watcher_stop.clear()
        worker = threading.Thread(
            target=_watch_loop,
            args=(live_dir, poll_interval_s),
            name="vyne-live",
            daemon=True,
        )
        _watcher = worker
        worker.start()


def _read_rev(live_dir: Path) -> str | None:
    try:
        rev = live_dir / _REV_FILE
        return rev.read_text(encoding="utf-8").strip() if rev.is_file() else None
    except OSError:  # pragma: no cover - best-effort dev tooling
        return None


def _watch_loop(live_dir: Path, poll_interval_s: float) -> None:
    host = _watcher_host
    last = _read_rev(live_dir)
    while not _watcher_stop.is_set():
        time.sleep(poll_interval_s)
        current = _read_rev(live_dir)
        if current == last:
            continue
        last = current
        # Debounce: a push writes several files then bumps REV last, but
        # give any stragglers a beat before tearing the UI down.
        time.sleep(0.2)
        if _watcher_stop.is_set():
            return
        if _reload_pending.is_set():
            continue  # a reload is already in flight; next session re-arms
        _reload_pending.set()
        # Read the host each time: after an Activity recreate the live host
        # is a new DirectRenderHost (see _start_watcher).
        host = _watcher_host
        try:
            host.getActivity().requestReload()
        except Exception:  # pragma: no cover - host interaction is best-effort
            logger.error("live: failed to request host reload", exc_info=True)
            _reload_pending.clear()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install(
    host: Any,
    *,
    module_name: str,
    poll_interval_s: float = 0.5,
) -> bool:
    """Arm live mode for one host session, or leave everything untouched.

    Call before the app module is imported (see ``vyne.android.start_direct``).
    Returns True when live mode is active. Never raises; a broken live setup
    must not fail app startup.
    """
    try:
        activity = host.getActivity() if hasattr(host, "getActivity") else None
        if activity is None:
            return False
        live_dir = _live_dir(activity)
        if live_dir is None or not _enabled(live_dir):
            return False
        if str(live_dir) not in sys.path:
            sys.path.insert(0, str(live_dir))
        evict_swappable(module_name, live_dir)
        _reload_pending.clear()
        _start_watcher(host, live_dir, poll_interval_s)
        logger.info("vyne live: hot reload armed at %s", live_dir)
        return True
    except Exception:  # pragma: no cover - host interaction is best-effort
        logger.debug("vyne live: install failed; running frozen", exc_info=True)
        return False
