"""A LangGraph chat agent that remembers each user across conversations.

pip install "alexein[langgraph]" langchain-openai
ALEXEIN_API_KEY=tm_... OPENAI_API_KEY=sk-... python examples/langgraph_agent.py
"""

from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from alexein.langgraph import AlexeinMemory, MemoryContext, MemoryState

memory = AlexeinMemory()
model = init_chat_model("openai:gpt-4.1-mini").bind_tools(memory.tools(write=True))


def agent(state: MemoryState) -> dict[str, Any]:
    system = "You are a helpful assistant.\n\n" + memory.prompt(state)
    return {"messages": [model.invoke([SystemMessage(system), *state["messages"]])]}


builder = StateGraph(MemoryState, context_schema=MemoryContext)
builder.add_node("recall", memory.recall)
builder.add_node("agent", agent)
builder.add_node("remember", memory.remember)
builder.add_edge(START, "recall")
builder.add_edge("recall", "agent")
builder.add_edge("agent", "remember")
builder.add_edge("remember", END)
graph = builder.compile(checkpointer=InMemorySaver())

if __name__ == "__main__":
    for said in ("I moved to Lisbon last month.", "Where do I live now?"):
        out = graph.invoke(
            {"messages": [HumanMessage(said)]},
            config={"configurable": {"thread_id": "example-1"}},
            context={"user_id": "example-dana"},
        )
        print(f"> {said}\n{out['messages'][-1].text}\n")
