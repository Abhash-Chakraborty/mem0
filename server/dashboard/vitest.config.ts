import { defineConfig } from "vitest/config";
import path from "node:path";

/**
 * The dashboard's first JavaScript test runner.
 *
 * Deferred from phase 00 deliberately: standing up a runner is its own change
 * and did not belong inside a production hotfix. What lands first is what that
 * hotfix could not assert — `normalizeGraph`, the guard that stops a malformed
 * /graph response from crashing the page, and `isBuildMismatch`, the drift
 * indicator.
 *
 * Node environment rather than jsdom: everything under test is a pure function.
 * A DOM would be a dependency these tests do not use and a slower start for
 * every future one.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    passWithNoTests: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
