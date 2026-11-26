/**
 * A chat in the terminal whose model remembers you across runs, with no memory tools: the client
 * is wrapped, so memory is read before each reply and each exchange is saved.
 *
 * npm install @alexein/sdk openai
 * ALEXEIN_API_KEY=tm_... OPENAI_API_KEY=sk-... npx tsx examples/wrapped-client.ts
 */

import { randomUUID } from "node:crypto";
import { createInterface } from "node:readline/promises";

import OpenAI from "openai";

import { Memory } from "../src/index.js"; // "@alexein/sdk" in your project
import { memoryOf, wrapOpenAI } from "../src/wrap/index.js"; // "@alexein/sdk/wrap"

const MODEL = "gpt-4.1-mini";

const memory = new Memory({ failOpen: true, timeout: 10_000 });
const gpt = wrapOpenAI(new OpenAI(), memory, {
  userId: "example-user", // your id for the person, from your own sign-in
  session: `chat-${randomUUID().slice(0, 8)}`,
});

const terminal = createInterface({ input: process.stdin, output: process.stdout });
const messages: OpenAI.ChatCompletionMessageParam[] = [
  { role: "system", content: "You are a helpful assistant." },
];
for (;;) {
  const said = (await terminal.question("you> ")).trim();
  if (!said) break;
  messages.push({ role: "user", content: said });
  const answer = await gpt.chat.completions.create({ model: MODEL, messages });
  const text = answer.choices[0]?.message.content ?? "";
  messages.push({ role: "assistant", content: text });
  console.log(`gpt> ${text}`);
}
terminal.close();
await memoryOf(gpt).flush(); // the last exchange's save, before the process ends
