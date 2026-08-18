"""Validation and lowering for the supported SVG path subset.

This module parses a deliberately small subset of SVG path data (only
M, L, C, Q, Z and their lowercase relative forms).  The subset is chosen
to cover common vector shapes without pulling in a full SVG parser.

The output is a list of JSON-safe command dicts ({"cmd": "M", "values": [...]})
that the Android side can interpret directly.  All validation happens here
in Python — the Android renderer trusts that incoming commands are valid.

Tokenization: a single regex extracts commands and numbers in one pass.
Supported number formats: integers, decimals, and scientific notation.
"""

from __future__ import annotations

import math
import re
from typing import Any

PATH_COMMAND_ARITY: dict[str, int] = {
    "M": 2, "m": 2,     # move to (absolute / relative)
    "L": 2, "l": 2,     # line to
    "C": 6, "c": 6,     # cubic bezier curve
    "Q": 4, "q": 4,     # quadratic bezier curve
    "Z": 0, "z": 0,     # close path
}
_COMMANDS = frozenset(PATH_COMMAND_ARITY)
_TOKEN = re.compile(
    rf"[{''.join(sorted(_COMMANDS))}]|"
    r"[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?"
)


def compile_path_data(data: str) -> list[dict[str, Any]]:
    """Compile supported SVG path data into JSON-safe drawing commands.

    Only ``M``, ``L``, ``C``, ``Q``, ``Z`` (plus relative forms) are supported.
    The parser handles:
    - Repeated coordinates under the same command (implicit continuation)
    - Implicit "L" after the first "M" segment (standard SVG behavior)
    - Compact notation (no separators: "M10-10")
    - Commas between coordinates
    """
    if not isinstance(data, str) or not data.strip():
        raise ValueError("Path d must be a non-empty SVG path string")

    tokens = _tokenize(data)
    commands: list[dict[str, Any]] = []
    index = 0
    command: str | None = None

    while index < len(tokens):
        token = tokens[index]
        if _is_command(token):
            command = token
            index += 1
        elif command is None:
            raise ValueError("Path data must begin with a command")

        assert command is not None
        upper = command.upper()
        arity = PATH_COMMAND_ARITY[upper]
        if arity == 0:
            commands.append({"cmd": command, "values": []})
            command = None
            continue

        first_move = upper == "M"
        parsed = False
        while index < len(tokens) and not _is_command(tokens[index]):
            end = index + arity
            if end > len(tokens) or any(
                _is_command(tokens[position]) for position in range(index, end)
            ):
                raise ValueError(f"Path command {command!r} has incomplete coordinates")
            values = [_number(tokens[position]) for position in range(index, end)]
            # SVG spec: after the first M segment, subsequent coordinate pairs
            # are treated as implicit L (or l) segments — not repeat M moves.
            output_command = command
            if first_move and parsed:
                output_command = "L" if command == "M" else "l"
            commands.append({"cmd": output_command, "values": values})
            index = end
            parsed = True

        if not parsed:
            raise ValueError(f"Path command {command!r} requires {arity} coordinates")

    return commands


def _tokenize(data: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    for match in _TOKEN.finditer(data):
        if not _separator_only(data[position : match.start()]):
            raise ValueError(f"Unsupported path syntax near {data[position:match.start()]!r}")
        tokens.append(match.group())
        position = match.end()
    if not tokens or not _separator_only(data[position:]):
        raise ValueError("Path data contains unsupported syntax")
    return tokens


def _separator_only(value: str) -> bool:
    return all(character.isspace() or character == "," for character in value)


def _is_command(value: str) -> bool:
    return len(value) == 1 and value in _COMMANDS


def _number(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Path coordinates must be finite")
    return result
