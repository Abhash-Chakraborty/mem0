import { describe, expect, it } from "vitest";
import {
  GIT_SHA,
  isBuildMismatch,
  shasDiffer,
  type ServerVersion,
} from "./build-info";

/**
 * The drift indicator, which is only useful if it stays quiet.
 *
 * A footer that cries "mismatch" whenever a SHA is missing trains people to
 * ignore it, and then it is worth nothing on the day the dashboard and the API
 * really were deployed from different commits. So the interesting cases here
 * are the ones where it must *not* fire.
 */

function serverAt(sha: string): ServerVersion {
  return {
    version: "1.0.0",
    git_sha: sha,
    built_at: "2026-08-18T00:00:00Z",
    python: "3.12.14",
    mem0_core: "2.0.18",
    started_at: "2026-08-18T00:00:00Z",
    uptime_seconds: 10,
  };
}

describe("isBuildMismatch", () => {
  it("says nothing when the server has not answered yet", () => {
    expect(isBuildMismatch(undefined)).toBe(false);
  });

  it("says nothing when the server does not know its own SHA", () => {
    // An image built outside Compose. Not a mismatched deploy.
    expect(isBuildMismatch(serverAt("unknown"))).toBe(false);
  });

  it("says nothing when this bundle does not know its SHA", () => {
    // In the test environment NEXT_PUBLIC_GIT_SHA is unset, so GIT_SHA is
    // "unknown" — which is exactly the case being asserted.
    expect(GIT_SHA).toBe("unknown");
    expect(isBuildMismatch(serverAt("a3f91c2"))).toBe(false);
  });
});

describe("shasDiffer — the rule behind the indicator", () => {
  it("reports drift when both sides know and disagree", () => {
    expect(shasDiffer("aaaaaaa", "bbbbbbb")).toBe(true);
  });

  it("stays quiet when both sides agree", () => {
    expect(shasDiffer("a3f91c2", "a3f91c2")).toBe(false);
  });

  it.each([
    ["the bundle", "unknown", "a3f91c2"],
    ["the server", "a3f91c2", "unknown"],
    ["both", "unknown", "unknown"],
  ])("stays quiet when %s does not know its SHA", (_who, bundle, server) => {
    expect(shasDiffer(bundle, server)).toBe(false);
  });
});
