import { defineConfig } from "tsup";

// ESM and CommonJS, each with its types, so `import` and `require` both work. No source maps:
// they would carry the whole TypeScript source, comments and all, into the package, and the
// output is not minified, so a stack trace reads as it is.
export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm", "cjs"],
  dts: true,
  clean: true,
  sourcemap: false,
  target: "node20",
});
