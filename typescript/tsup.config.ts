import { defineConfig } from "tsup";

// ESM and CommonJS, each with its types, so `import` and `require` both work, for the client and
// each integration. `splitting` puts the client in a chunk the entries share, in both formats, so
// `@alexein/sdk` and `@alexein/sdk/langgraph` hand out the same classes (`instanceof` holds across
// them). The frameworks are peer dependencies, never bundled. No source maps: they would carry the
// whole TypeScript source into the package, and the output is not minified, so a stack trace
// reads as it is.
export default defineConfig({
  entry: {
    index: "src/index.ts",
    langgraph: "src/langgraph/index.ts",
    "openai-agents": "src/openai-agents/index.ts",
  },
  format: ["esm", "cjs"],
  dts: true,
  splitting: true,
  clean: true,
  sourcemap: false,
  target: "node20",
  external: [/^@langchain\//, /^@openai\//, "zod"],
});
