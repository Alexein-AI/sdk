/**
 * A stand-in for the model an OpenAI Agents SDK agent talks to, of which the SDK for JavaScript
 * has none: it answers each call with the next step of a script.
 */

import {
  type AgentOutputItem,
  type Model,
  type ModelRequest,
  type ModelResponse,
  type StreamEvent,
  Usage,
} from "@openai/agents";

/** A model that answers each call with the next step, and keeps what it was asked. */
export class Scripted implements Model {
  readonly calls: ModelRequest[] = [];
  constructor(private readonly steps: AgentOutputItem[][]) {}

  async getResponse(request: ModelRequest): Promise<ModelResponse> {
    this.calls.push(request);
    const output = this.steps.shift();
    if (!output) throw new Error("the script has no step left");
    return { usage: new Usage(), output, responseId: `resp-${this.calls.length}` };
  }

  async *getStreamedResponse(request: ModelRequest): AsyncIterable<StreamEvent> {
    const { output, responseId } = await this.getResponse(request);
    const usage = { inputTokens: 0, outputTokens: 0, totalTokens: 0 };
    // The protocol's output type is narrower than the runner's; the items are the same.
    yield { type: "response_done", response: { id: responseId!, usage, output } } as StreamEvent;
  }
}

export function says(text: string): AgentOutputItem {
  return {
    type: "message",
    role: "assistant",
    status: "completed",
    content: [{ type: "output_text", text }],
  };
}

export function calls(name: string, args: Record<string, unknown>, callId: string) {
  return {
    type: "function_call",
    callId,
    name,
    arguments: JSON.stringify(args),
    status: "completed",
  } as AgentOutputItem;
}
