"""What `init crewai` knows about CrewAI: which crews it can serve, the CrewAI it needs, and the
lines a developer adds to turn memory on.

Not the written file - that is `templates/crewai/memory.py.tmpl` - and not the steps every
framework shares, which are `scaffold.py`'s.
"""

from __future__ import annotations

from pathlib import Path

from alexein_cli import env, project
from alexein_cli.stop import Stop
from alexein_cli.ui import Console

# `alexein.crewai` subclasses CrewAI's `Memory`, which CrewAI does not document as a place to
# extend: it was verified against 1.15, and a newer CrewAI is used with a warning, not refused.
CREWAI_MINIMUM = "1.15"
CREWAI_TESTED = "1.15"


def crew(root: Path) -> project.Crew:
    """The crew to serve at `root`, or `Stop` with why there is none."""
    found = project.crew(root)
    if found is None:
        raise Stop(
            "not a CrewAI crew (no [tool.crewai] in pyproject.toml, and no @CrewBase crew). "
            "Start one with `alexein-cli create crewai <name>`. Nothing changed."
        )
    if found.kind == "flow":
        raise Stop("this is a CrewAI Flow; Flows are not supported yet. Nothing changed.")
    return found


def require_version(root: Path, console: Console) -> None:
    """Stop on a CrewAI older than the file needs; warn on one newer than it was tested with."""
    site = project.environment(root)
    version = project.installed(site, "crewai") if site else None
    if version is None:
        console.step(
            "warning",
            "crewai version not checked: no .venv found here; "
            "run `alexein-cli doctor` once it is installed",
        )
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
            "it should work - if tasks stop recalling or saving memory, "
            "look for warnings on the `alexein` logger",
        )


def newer_than_tested(version: str) -> bool:
    """Whether `version` is a newer minor release of CrewAI than this one was tested with."""
    return _minor(version) > _minor(CREWAI_TESTED)


def _minor(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in version.split(".")[:2] if n.isdigit())


def next_steps(found: project.Crew, module: str) -> str:
    """The lines that turn memory on, for this kind of crew."""
    if found.kind == "json":
        name = module.rsplit(".", 1)[-1]
        wiring = [
            "  Wire it in, in crew.jsonc:",
            "",
            f'    "memory": {{"python": "{name}.alexein_memory"}},',
            f'    "before_kickoff_callbacks": [{{"python": "{name}.whose"}}]',
        ]
        run = [
            "    from crewai.project.crew_loader import load_crew",
            "",
            '    crew, _ = load_crew("crew.jsonc")',
            '    crew.kickoff(inputs={"user_id": "dana", ...})',
        ]
    else:
        wiring = [
            "  Wire it in, in crew.py:",
            "",
            f"    from {module} import alexein_memory, whose",
            "",
            "    @CrewBase",
            "    class MyCrew:",
            "        memory = alexein_memory",
            "",
            "        @before_kickoff",
            "        def whose_memory(self, inputs):",
            "            return whose(inputs)",
            "",
            "        @crew",
            "        def crew(self) -> Crew:",
            "            return Crew(..., memory=self.memory)",
        ]
        run = ['    MyCrew().crew().kickoff(inputs={"user_id": "dana", ...})']
    return "\n".join(
        [
            *wiring,
            "",
            "  Run with the app user's id; the model never chooses it:",
            "",
            *run,
            "",
            "  Or, without CrewAI's memory: Agent(..., tools=alexein_memory.tools(user_id)),",
            "  and alexein_memory.save_result(user_id, output) after the run.",
            "",
            f"  The key is {env.KEY} in .env; a plain script loads it itself.",
            "  `alexein-cli doctor` checks it all.",
        ]
    )
