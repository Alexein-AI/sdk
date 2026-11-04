import { defineConfig } from "tsup";

// One ESM file to run: `bin.ts`, with what it imports bundled in, and `twinmemory` left to npm.
export default defineConfig({
  entry: ["src/bin.ts"],
  format: ["esm"],
  clean: true,
  target: "node20",
  external: ["twinmemory"],
});
