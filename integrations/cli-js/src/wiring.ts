/**
 * What `init` tells the developer to wire in once the file is written: the import, and the lines
 * that use it, for the framework and the preset. Text only; nothing here touches the project.
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

function langgraph(o: Options): string {
  const nodes = o.parts.includes("nodes");
  const tools = o.parts.includes("tools");
  const module = moduleOf(o);
  const names = [
    "MemoryContext",
    ...(nodes ? ["MemoryState", "memoryPrompt", "recall", "remember"] : []),
    ...(tools ? ["MEMORY_TOOLS"] : []),
  ];
  const lines = [
    "  Wire it in, where you build your graph:",
    "",
    `    import { ${names.join(", ")} } from "${module}";`,
    "",
  ];
  if (nodes) {
    lines.push(
      "    const graph = new StateGraph(MemoryState, MemoryContext)",
      '      .addNode("recall", recall)',
      '      .addNode("remember", remember)',
      '      .addEdge(START, "recall")',
      '      .addEdge("recall", "agent")   // your model node: memoryPrompt(state)',
      '      .addEdge("agent", "remember") // goes in its system prompt',
      "",
    );
  }
  if (tools) {
    lines.push(
      "    // the model looks things up itself: give it the tools",
      "    createAgent({ model, tools: [...MEMORY_TOOLS], contextSchema: MemoryContext });",
      "",
    );
  }
  lines.push(
    "  Run with the end user's id; the model never chooses it:",
    "",
    '    await graph.invoke(inputs, { context: { user_id: "dana" },',
    '                                 configurable: { thread_id: "t-1" } });',
    "",
    `  The key is ${env.KEY} in .env. \`langgraph dev\` reads .env when langgraph.json`,
    '  has "env": ".env"; a plain script loads it itself.',
    "  `npx twinmemory-cli doctor` checks it all.",
  );
  return lines.join("\n");
}

function openaiAgents(o: Options): string {
  const nodes = o.parts.includes("nodes");
  const tools = o.parts.includes("tools");
  const names = [
    ...(tools ? ["MEMORY_TOOLS"] : []),
    "type MemoryContext",
    ...(nodes ? ["recall", "remember"] : []),
  ];
  const lines = [
    "  Wire it in, where you run your agent:",
    "",
    `    import { ${names.join(", ")} } from "${moduleOf(o)}";`,
    "",
  ];
  if (tools) {
    lines.push('    const agent = new Agent({ name: "Assistant", tools: [...MEMORY_TOOLS] });', "");
  }
  lines.push(
    "    const result = await run(agent, message, {",
    '      context: { userId: "dana" } satisfies MemoryContext, // the end user; never the model',
    ...(nodes ? ["      callModelInputFilter: recall,"] : []),
    "    });",
    ...(nodes ? ["    await remember(result);"] : []),
    "",
    `  The key is ${env.KEY} in .env; load it (dotenv) before the first run.`,
    "  `npx twinmemory-cli doctor` checks it all.",
  );
  return lines.join("\n");
}
