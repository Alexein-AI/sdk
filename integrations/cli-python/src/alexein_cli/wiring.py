"""What `init` tells the developer to wire in once the file is written: the import, and the
lines that use it, for LangGraph and the OpenAI Agents SDK (CrewAI's are `crews.py`'s). Text
only; nothing here touches the project.
"""

from __future__ import annotations

from alexein_cli import env


def next_steps(module: str, framework: str) -> str:
    if framework == "openai-agents":
        return _openai_agents(module)
    return "\n".join(
        [
            "  Wire it in, where you build your graph:",
            "",
            f"    from {module} import MemoryContext, MemoryState, memory",
            "",
            "    builder = StateGraph(MemoryState, context_schema=MemoryContext)",
            '    builder.add_node("recall", memory.recall)',
            '    builder.add_node("remember", memory.remember)',
            '    builder.add_edge(START, "recall")',
            '    builder.add_edge("recall", "agent")    # your model node: memory.prompt(state)',
            '    builder.add_edge("agent", "remember")  # goes in its system prompt',
            "",
            "    # or let the model look things up itself (write=True: and save)",
            "    create_agent(model, tools=memory.tools(), context_schema=MemoryContext)",
            "",
            "  Run with the app user's id; the model never chooses it:",
            "",
            '    graph.invoke(inputs, config={"configurable": {"thread_id": "t-1"}},',
            '                 context={"user_id": "dana"})',
            "",
            f"  The key is {env.KEY} in .env. `langgraph dev` loads .env when",
            '  langgraph.json has "env": ".env"; a plain script loads it itself.',
            "  `alexein-cli doctor` checks it all.",
        ]
    )


def _openai_agents(module: str) -> str:
    return "\n".join(
        [
            "  Wire it in, where you run your agent:",
            "",
            f"    from {module} import MemoryContext, memory",
            "",
            '    agent = Agent(name="Assistant", tools=memory.tools())  # write=True: and save',
            "    result = await Runner.run(",
            "        agent,",
            "        message,",
            '        context=MemoryContext(user_id="dana"),  # the app user; never the model',
            "        run_config=RunConfig(call_model_input_filter=memory.recall),",
            "    )",
            "    await memory.remember(result)",
            "",
            f"  The key is {env.KEY} in .env; load it (python-dotenv) before the",
            "  first run. `alexein-cli doctor` checks it all.",
        ]
    )
