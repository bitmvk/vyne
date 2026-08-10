"""Canonical project template resources for ``vyne new``.

The literal template files in this package are the single source for the
files scaffolded by ``vyne new``.  They ship as package resources so the
CLI works from an installed wheel, not only a checkout.  ``load()``
returns the raw file text; the one parameterized value is ``{nameLiteral}``
in ``settings.gradle.kts``.
"""

from __future__ import annotations

from importlib.resources import files


def load(name: str) -> str:
    """Return the raw text of one project template resource."""
    return files("vyne.cli.templates").joinpath(name).read_text(encoding="utf-8")
