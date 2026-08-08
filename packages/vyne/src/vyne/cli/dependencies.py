"""Structure-preserving PEP 508-aware pyproject.toml dependency editing.

Ensures a Vyne dependency exists in an existing pyproject.toml file using a
round-tripping TOML document model (tomlkit) and PEP 508 name normalization
(packaging.requirements.Requirement).  This replaces regex/line-based
manipulation that could corrupt tool tables or misidentify unrelated packages.
"""

from __future__ import annotations

from typing import Any

import tomlkit
from packaging.requirements import Requirement, InvalidRequirement
from packaging.utils import canonicalize_name


_VYNE_CANONICAL = "vyne"


def ensure_vyne_dependency(pyproject_text: str, requirement: str) -> str:
    """Return *pyproject_text* with *requirement* appended to
    ``[project].dependencies``, or unchanged if an equivalent Vyne
    dependency already exists.

    Raises ``RuntimeError`` with a contextual message when the TOML is
    malformed, ``dependencies`` is not a string array, or an element is not
    a valid PEP 508 requirement string.
    """
    try:
        doc = tomlkit.parse(pyproject_text)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot parse existing pyproject.toml as TOML: {exc}"
        ) from exc

    if _ensure_doc_has_vyne(doc, requirement):
        return _render_doc(pyproject_text, doc)

    # Unchanged --- preserve byte-for-byte for a no-op
    return pyproject_text


def _has_dependency(pyproject_text: str) -> bool:
    """Return True if ``[project].dependencies`` already contains a Vyne
    requirement, using PEP 508 canonicalized name comparison."""
    try:
        doc = tomlkit.parse(pyproject_text)
    except Exception:
        return False

    return _doc_has_vyne(doc)


def _is_project_mapping(obj: Any) -> bool:
    """Return True if *obj* is a TOML Table or InlineTable suitable as
    ``[project]``."""
    return isinstance(obj, (tomlkit.items.Table, tomlkit.items.InlineTable))


def _ensure_doc_has_vyne(doc: tomlkit.TOMLDocument, requirement: str) -> bool:
    """Mutate *doc* to include a Vyne dependency.  Return True when the
    document was modified."""
    project = doc.get("project")
    if project is None:
        project = tomlkit.table()
        doc["project"] = project
    elif not _is_project_mapping(project):
        # Never replace a present project object: doing so could discard
        # unrelated project metadata.  Reject unsupported TOML shapes before
        # mutating the document.
        raise RuntimeError(
            "pyproject.toml [project] must be a table or inline table; "
            f"unsupported shape: {type(project).__name__}"
        )

    deps = project.get("dependencies")
    if deps is None:
        deps_arr = tomlkit.array()
        deps_arr.append(requirement)
        if isinstance(project, tomlkit.items.Table):
            deps_arr.multiline(True)
        project["dependencies"] = deps_arr  # type: ignore[index]
        return True

    if not isinstance(deps, tomlkit.items.Array):
        raise RuntimeError(
            "project.dependencies in pyproject.toml must be an array of strings"
        )

    parsed = _parse_dependency_array(deps)
    if _parsed_contains_vyne(parsed):
        return False

    deps.append(requirement)
    return True


def _doc_has_vyne(doc: tomlkit.TOMLDocument) -> bool:
    """Return True if the document already has a Vyne dependency."""
    project = doc.get("project")
    if not _is_project_mapping(project):
        return False
    deps = project.get("dependencies")
    if not isinstance(deps, tomlkit.items.Array):
        return False
    try:
        parsed = _parse_dependency_array(deps)
    except Exception:
        return False
    return _parsed_contains_vyne(parsed)


def _parse_dependency_array(
    deps: tomlkit.items.Array,
) -> list[Requirement | None]:
    """Parse each string element of *deps* as a PEP 508 requirement.
    Non-string elements raise; unparseable strings are stored as ``None``
    so the caller can decide the error policy.
    """
    results: list[Requirement | None] = []
    for idx, entry in enumerate(deps):
        if not isinstance(entry, tomlkit.items.String):
            raise RuntimeError(
                f"project.dependencies[{idx}] must be a string, "
                f"got {type(entry).__name__}"
            )
        try:
            results.append(Requirement(str(entry)))
        except InvalidRequirement as exc:
            raise RuntimeError(
                f"project.dependencies[{idx}] is not a valid PEP 508 "
                f"requirement: {exc}"
            ) from exc
    return results


def _parsed_contains_vyne(parsed: list[Requirement | None]) -> bool:
    """Return True when any parsed requirement has canonical name 'vyne'."""
    for req in parsed:
        if req is not None and canonicalize_name(req.name) == _VYNE_CANONICAL:
            return True
    return False


def _render_doc(original_text: str, doc: tomlkit.TOMLDocument) -> str:
    """Render *doc* to a string.  Prefer the final newline convention of the
    original text so whitespace-only diffs are minimized."""
    result = tomlkit.dumps(doc)
    if original_text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    elif not original_text.endswith("\n") and result.endswith("\n"):
        result = result.rstrip("\n")
    return result
