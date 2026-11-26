"""What the memory commands print for a person to read. Memories - a search's, the latest - as a
list: each one's kind, day and ref, then its text. Anything else as an outline of the JSON that came
back, every field of it, so a field the API adds later shows without a change here. With `--json`
none of this is used: the commands print the API's JSON as it came. The TypeScript CLI prints the
same.
"""

from __future__ import annotations

import json
from typing import Any, cast


def _scalar(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _indented(text: str, indent: str) -> str:
    """A string that runs over lines, its later lines under its first."""
    return text.replace("\n", f"\n{indent}")


def outline(value: Any, indent: str = "") -> list[str]:
    """JSON as indented lines, as YAML would show it, with nothing quoted."""
    if isinstance(value, list):
        entries = cast(list[Any], value)
        if not entries:
            return [f"{indent}(none)"]
        lines: list[str] = []
        for entry in entries:
            first, *rest = outline(entry, f"{indent}  ")
            lines += [f"{indent}- {first[len(indent) + 2 :]}", *rest]
        return lines
    if isinstance(value, dict):
        fields = cast(dict[str, Any], value)
        if not fields:
            return [f"{indent}(empty)"]
        lines = []
        for name, entry in fields.items():
            if isinstance(entry, list) and not entry:
                lines.append(f"{indent}{name}: (none)")
            elif isinstance(entry, dict | list):
                lines += [f"{indent}{name}:", *outline(entry, f"{indent}  ")]
            else:
                lines.append(f"{indent}{name}: {_indented(_scalar(entry), f'{indent}  ')}")
        return lines
    return [f"{indent}{_indented(_scalar(value), indent)}"]


def _memory(entry: Any) -> list[str]:
    """One memory as a heading - its kind, its day, its ref - and its text under it."""
    if not isinstance(entry, dict):
        return outline(entry)
    fields = cast(dict[str, Any], entry)

    def string(name: str) -> str:
        value = fields.get(name)
        return value if isinstance(value, str) else ""

    session = f"  (session {string('session')})" if string("session") else ""
    parts = (f"{string('type') or 'memory':<8}", string("date")[:10], string("ref"))
    heading = "  ".join(part for part in parts if part) + session
    text = fields.get("text")
    return [heading.rstrip(), f"  {_indented(_scalar('' if text is None else text), '  ')}"]


def memories(found: Any, empty: str) -> list[str]:
    """Memories, one after another with a line between; `empty` when there are none."""
    if not isinstance(found, list) or not found:
        return [empty]
    lines: list[str] = []
    for n, entry in enumerate(cast(list[Any], found)):
        lines += ([""] if n else []) + _memory(entry)
    return lines
