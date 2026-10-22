"""Templates into source: the parts a preset leaves out cut away, and the values filled in.

A template marks each optional part with a pair of comment lines, `# >>> nodes` and
`# <<< nodes`, around whole lines; what is not asked for is dropped with its markers, and the
markers of what is kept are dropped too, so the written file carries none of this. Values are
`{name}` placeholders, filled by plain replacement - not `str.format`, since the code around
them is full of braces of its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

TEMPLATES = Path(__file__).parent / "templates"

_MARK = re.compile(r"^\s*# (>>>|<<<) ([a-z_]+)\s*$")


def render(template: str, parts: Iterable[str], values: Mapping[str, str]) -> str:
    """The template at `templates/<template>`, keeping only `parts`, with `values` filled."""
    kept = set(parts)
    out: list[str] = []
    skipping: list[str] = []
    for line in (TEMPLATES / template).read_text().splitlines():
        mark = _MARK.match(line)
        if mark:
            opens, part = mark.group(1) == ">>>", mark.group(2)
            if opens and part not in kept:
                skipping.append(part)
            elif not opens and skipping and skipping[-1] == part:
                skipping.pop()
            continue
        if not skipping:
            out.append(line)
    text = "\n".join(out) + "\n"
    for name, value in values.items():
        text = text.replace("{" + name + "}", value)
    return text
