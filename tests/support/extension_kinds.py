"""Shared extension-kind fixtures for the extension test suites.

The Kotlin ElementRegistry is the single source of truth: Python syncs
kind -> (props, events) tables at startup.  These helpers give the
registry/lowering/protocol suites one canonical extension fixture and a
safe module-level activation pattern.
"""

from __future__ import annotations

from vyne.extensions_registry import sync_from_host

# One synthetic extension kind used across EXT-01/02/03 suites.
KINDS = {
    "TimerRing": (["progress", "ring_color"], ["complete"], [False]),
}


def activate_extension_kinds() -> None:
    """Sync the shared extension fixture into the registry."""
    sync_from_host(KINDS)


def deactivate_extension_kinds() -> None:
    """Remove the shared extension fixture from the registry."""
    sync_from_host({})
