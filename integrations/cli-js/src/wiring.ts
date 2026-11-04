/**
 * What `init` tells the developer to wire in once the file is written: the import, and the lines
 * that use `memory`, for the framework and the preset. Text only; nothing here touches the project.
 */

import * as env from "./env.js";
import type { Options } from "./scaffold.js";

/** How the developer's code imports the written file. */
function moduleOf(o: Options): string {
  return "./" + o.filename.replace(/\.([cm]?)ts$/, ".$1js");
}

export function nextSteps(o: Options): string {
  return o.framework === "openai-agents" ? openaiAgents(o) : langgraph(o);
}

/** With the nodes, every turn is saved already; alone, the tools are what saves. */
function toolsOf(o: Options): string {
  return o.parts.includes("nodes") ? "memory.tools()" : "memory.tools({ write: true })";
}

function langgraph(o: Options): string {
  const nodes = o.parts.includes("nodes");
  const tools = o.parts.includes("tools");
  const names = ["memory", ...(nodes ? ["MemoryAnnotation"] : []), "MemoryContext"];
  const lines = [
    "  Wire it in, where you build your graph:",
    "",
    `    import { ${names.join(", ")} } from "${moduleOf(o)}";`,
    "",
  ];
  if (nodes) {
    lines.push(
      "    const graph = new StateGraph(MemoryAnnotation, MemoryContext)",
      '      .addNode("recall", memory.recall)',
      '      .addNode("remember", memory.remember)',
      '      .addEdge(START, "recall")',
      '      .addEdge("recall", "agent")   // your model node: memory.prompt(state)',
      '      .addEdge("agent", "remember") // goes in its system prompt',
      "",
    );
  }
  if (tools) {
    lines.push(
      "    // the model looks things up itself: give it the tools",
      `    createAgent({ model, tools: ${toolsOf(o)}, contextSchema: MemoryContext });`,
      "",
    );
  }
  lines.push(
    "  Run with the app user's id; the model never chooses it:",
    "",
    '    await graph.invoke(inputs, { context: { user_id: "dana" },',
    '                                 configurable: { thread_id: "t-1" } });',
    "",
    `  The key is ${env.KEY} in .env. \`langgraph dev\` reads .env when langgraph.json`,
    '  has "env": ".env"; a script loads it (import "dotenv/config") before the first run.',
    "  `npx @alexein/cli doctor` checks it all.",
  );
  return lines.join("\n");
}

function openaiAgents(o: Options): string {
  const nodes = o.parts.includes("nodes");
  const tools = o.parts.includes("tools");
  const lines = [
    "  Wire it in, where you run your agent:",
    "",
    `    import { memory, type MemoryContext } from "${moduleOf(o)}";`,
    "",
  ];
  if (tools) {
    lines.push(`    const agent = new Agent({ name: "Assistant", tools: ${toolsOf(o)} });`, "");
  }
  lines.push(
    "    const result = await run(agent, message, {",
    '      context: { userId: "dana" } satisfies MemoryContext, // the app user; never the model',
    ...(nodes ? ["      callModelInputFilter: memory.recall,"] : []),
    "    });",
    ...(nodes ? ["    await memory.remember(result);"] : []),
    "",
    `  The key is ${env.KEY} in .env; load it (import "dotenv/config") before the first run.`,
    "  `npx @alexein/cli doctor` checks it all.",
  );
  return lines.join("\n");
}
