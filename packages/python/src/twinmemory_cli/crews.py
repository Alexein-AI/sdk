"""What `init crewai` knows about CrewAI: which crews it can serve, the CrewAI it needs, the
presets that apply, and the lines a developer adds to turn memory on.

Not the written file - that is `templates/crewai/memory.py.tmpl` - and not the steps every
framework shares, which are `scaffold.py`'s.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from twinmemory_cli import project
from twinmemory_cli.stop import Stop
from twinmemory_cli.ui import Console

if TYPE_CHECKING:
    from twinmemory_cli.scaffold import Options

# The written file subclasses CrewAI's `Memory`, which CrewAI does not document as a place to
# extend: it was verified against 1.15, and a newer CrewAI is used with a warning, not refused.
CREWAI_MINIMUM = "1.15"
CREWAI_TESTED = "1.15"


def parts(options: Options) -> tuple[str, ...]:
    """The template's parts for the flags given; LangGraph's own flags stop the command."""
    refused = [
        flag
        for flag, given in (
            ("--nodes-only", options.parts == ("nodes",)),
            ("--async", options.asynchronous),
            ("--graph", options.graph is not None),
        )
        if given
    ]
    if refused:
        raise Stop(f"{', '.join(refused)}: for LangGraph, not CrewAI", code=2)
    return ("tools", "tools_only") if options.parts == ("tools",) else ("auto", "tools")


def crew(root: Path) -> project.Crew:
    """The crew to serve at `root`, or `Stop` with why there is none."""
    found = project.crew(root)
    if found is None:
        raise Stop(
            "not a CrewAI crew (no [tool.crewai] in pyproject.toml, and no @CrewBase crew). "
            "Start one with `twinmemory-cli create crewai <name>`. Nothing changed."
        )
    if found.kind == "flow":
        raise Stop("this is a CrewAI Flow; Flows are not supported yet. Nothing changed.")
    return found


def require_version(root: Path, console: Console) -> None:
    """Stop on a CrewAI older than the file needs; warn on one newer than it was tested with."""
    site = project.environment(root)
    version = project.installed(site, "crewai") if site else None
    if version is None:
        return
    if project.older(version, CREWAI_MINIMUM):
        tool = project.installer(root, []).name
        raise Stop(
            f"this project has crewai {version} (needs >={CREWAI_MINIMUM}) installed. Upgrade "
            f"first - {tool} add 'crewai>={CREWAI_MINIMUM}' - then run init again. "
            "Nothing changed."
        )
    if newer_than_tested(version):
        console.step(
            "warning",
            f"crewai {version} is newer than this release was tested with ({CREWAI_TESTED}); "
            "run `twinmemory-cli doctor` after upgrading",
        )


def newer_than_tested(version: str) -> bool:
    """Whether `version` is a newer minor release of CrewAI than this one was tested with."""
    return _minor(version) > _minor(CREWAI_TESTED)


def _minor(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in version.split(".")[:2] if n.isdigit())


def next_steps(found: project.Crew, module: str, options: Options) -> str:
    """The lines that turn memory on, for this kind of crew and preset."""
    if "auto" not in options.parts:
        return "\n".join(
            [
                "  Give an agent the tools, with the user your code knows:",
                "",
                f"    from {module} import memory_tools, save_result",
                "",
                '    Agent(..., tools=memory_tools("dana"))',
                '    save_result("dana", crew.kickoff(inputs={...}))   # keep what it found',
                "",
                *_closing(),
            ]
        )
    if found.kind == "json":
        name = module.rsplit(".", 1)[-1]
        wiring = [
            "  Wire it in, in crew.jsonc:",
            "",
            f'    "memory": {{"python": "{name}.twin_memory"}},',
            f'    "before_kickoff_callbacks": [{{"python": "{name}.whose"}}]',
        ]
    else:
        wiring = [
            "  Wire it in, in crew.py:",
            "",
            f"    from {module} import TwinMemory, whose",
            "",
            "    @CrewBase",
            "    class MyCrew:",
            "        memory = TwinMemory()",
            "",
            "        @before_kickoff",
            "        def whose_memory(self, inputs):",
            "            return whose(inputs)",
            "",
            "        @crew",
            "        def crew(self) -> Crew:",
            "            return Crew(..., memory=self.memory)",
        ]
    return "\n".join(
        [
            *wiring,
            "",
            "  Run with the end user's id; the model never chooses it:",
            "",
            '    MyCrew().crew().kickoff(inputs={"user_id": "dana", ...})',
            "",
            *_closing(),
        ]
    )


def _closing() -> list[str]:
    return [
        "  The key is TWIN_MEMORY_API_KEY in .env; a plain script loads it itself.",
        "  `twinmemory-cli doctor` checks it all.",
    ]
