/** LangGraph.js graphs and an `AlexeinMemory` over a recorded client, for the tests. */

import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { END, MessagesValue, START, StateGraph, StateSchema } from "@langchain/langgraph";
import { ToolNode } from "@langchain/langgraph/prebuilt";

import { AlexeinMemory, MemoryAnnotation, MemoryContext } from "../../src/langgraph/index.js";
import { REF, type Respond, answer, recorded } from "./recorded.js";

export const RUN = { context: { user_id: "dana" }, configurable: { thread_id: "t-1" } };
export const CALLS = [
  { name: "memory_search", args: { query: "home" }, id: "c1" },
  { name: "memory_open", args: { ref: REF }, id: "c2" },
  { name: "memory_add", args: { text: "Prefers trains." }, id: "c3" },
];

/** An `AlexeinMemory` over a recorded client. */
export function load(respond: Respond = answer, { failOpen = true, strict = false } = {}) {
  const { memory, sent } = recorded(respond, "langgraph", failOpen);
  return { m: new AlexeinMemory(memory, { strict }), sent };
}

export function turnGraph(
  m: AlexeinMemory,
  agent: (state: any) => Promise<{ messages: BaseMessage[] }>,
) {
  return new StateGraph(MemoryAnnotation, MemoryContext)
    .addNode("recall", m.recall)
    .addNode("agent", agent)
    .addNode("remember", m.remember)
    .addEdge(START, "recall")
    .addEdge("recall", "agent")
    .addEdge("agent", "remember")
    .addEdge("remember", END)
    .compile();
}

export function toolsGraph(m: AlexeinMemory) {
  const State = new StateSchema({ messages: MessagesValue });
  return new StateGraph(State, MemoryContext)
    .addNode("agent", async () => ({
      messages: [new AIMessage({ content: "", tool_calls: CALLS })],
    }))
    .addNode("tools", new ToolNode(m.tools({ write: true })))
    .addEdge(START, "agent")
    .addEdge("agent", "tools")
    .addEdge("tools", END)
    .compile();
}

export const toolResults = (out: { messages: any[] }) =>
  Object.fromEntries(out.messages.slice(-3).map((msg) => [msg.tool_call_id, msg.content]));
