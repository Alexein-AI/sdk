"""What `init` tells the developer to wire in once the file is written: the import, and the
lines that use it, for the framework and the preset. Text only; nothing here touches the
project.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from twinmemory_cli import env

if TYPE_CHECKING:
    from twinmemory_cli.scaffold import Options


def next_steps(module: str, options: Options) -> str:
    if options.framework == "openai-agents":
        return _openai_agents(module, options)
    nodes, tools = "nodes" in options.parts, "tools" in options.parts
    run = "await graph.ainvoke" if options.asynchronous else "graph.invoke"
    names = ["MemoryContext"]
    names += ["MemoryState", "memory_prompt", "recall", "remember"] if nodes else []
    names += ["MEMORY_TOOLS"] if tools else []
    lines = [
        "  Wire it in, where you build your graph:",
        "",
        f"    from {module} import {', '.join(sorted(names))}",
        "",
    ]
    if nodes:
        lines += [
            "    builder = StateGraph(MemoryState, context_schema=MemoryContext)",
            '    builder.add_node("recall", recall)',
            '    builder.add_node("remember", remember)',
            '    builder.add_edge(START, "recall")',
            '    builder.add_edge("recall", "agent")    # your model node: memory_prompt(state)',
            '    builder.add_edge("agent", "remember")  # goes in its system prompt',
            "",
        ]
    if tools:
        lines += [
            "    # the model looks things up itself: give it the tools",
            "    create_agent(model, tools=[*MEMORY_TOOLS, ...], context_schema=MemoryContext)",
            "",
        ]
    lines += [
        "  Run with the end user's id; the model never chooses it:",
        "",
        f'    {run}(inputs, config={{"configurable": {{"thread_id": "t-1"}}}},',
        '                 context={"user_id": "dana"})',
        "",
        f"  The key is {env.KEY} in .env. `langgraph dev` reads .env when langgraph.json",
        '  has "env": ".env"; a plain script loads it itself.',
        "  `twinmemory-cli doctor` checks it all.",
    ]
    return "\n".join(lines)


def _openai_agents(module: str, options: Options) -> str:
    nodes, tools = "nodes" in options.parts, "tools" in options.parts
    names = ["MemoryContext"]
    names += ["recall", "remember"] if nodes else []
    names += ["MEMORY_TOOLS"] if tools else []
    lines = [
        "  Wire it in, where you run your agent:",
        "",
        f"    from {module} import {', '.join(sorted(names))}",
        "",
    ]
    if tools:
        lines += ['    agent = Agent(name="Assistant", tools=[*MEMORY_TOOLS, ...])', ""]
    lines += [
        "    result = await Runner.run(",
        "        agent,",
        "        message,",
        '        context=MemoryContext(user_id="dana"),  # the end user; never the model',
    ]
    if nodes:
        lines += ["        run_config=RunConfig(call_model_input_filter=recall),"]
    lines += ["    )"]
    if nodes:
        lines += ["    await remember(result)"]
    lines += [
        "",
        f"  The key is {env.KEY} in .env; load it (python-dotenv) before the",
        "  first run. `twinmemory-cli doctor` checks it all.",
    ]
    return "\n".join(lines)
