import { defineConfig } from "tsup";

// ESM and CommonJS, each with its types, so `import` and `require` both work.
export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm", "cjs"],
  dts: true,
  clean: true,
  sourcemap: true,
  target: "node20",
});
