import { defineConfig } from "vitest/config";

// `unstubEnvs` and `unstubGlobals`: the key and the `fetch` a test stubs are its own.
export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    testTimeout: 30_000,
    unstubEnvs: true,
    unstubGlobals: true,
  },
});
