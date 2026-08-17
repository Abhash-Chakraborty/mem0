import { describe, expect, it } from "vitest";
import { normalizeGraph, pruneEdges } from "./graph";

/**
 * The regression suite for the production crash.
 *
 * `/dashboard/graph` showed a full-page "Application error" because the page
 * did `[...graph.nodes]` on a response that had no `nodes` key — a proxy error
 * page served as 200, or a gateway body. `??` does not help there: the object
 * exists, the key does not, and the spread throws during render with no error
 * boundary above it.
 *
 * Phase 00 fixed it and verified the fix by transpiling the module and running
 * assertions by hand, because the dashboard had no test runner. These are those
 * assertions, now permanent.
 */

const goodNode = { id: "n1", label: "Alice", type: "PROPER", memories: 3 };
const goodEdge = {
  source: "n1",
  target: "n2",
  relationship: "co-occurs",
  weight: 2,
};

describe("normalizeGraph — the shapes that crashed the page", () => {
  it.each([
    ["an error object with no nodes key", { detail: "upstream failed" }],
    [
      "an HTML page served as JSON",
      "<html><body>502 Bad Gateway</body></html>",
    ],
    ["null", null],
    ["undefined", undefined],
    ["a bare array", [1, 2, 3]],
    ["a number", 42],
    ["an empty object", {}],
  ])("survives %s", (_label, input) => {
    const result = normalizeGraph(input);
    expect(Array.isArray(result.nodes)).toBe(true);
    expect(Array.isArray(result.edges)).toBe(true);
    // The crash was a spread on a non-iterable. Prove the result always is one.
    expect(() => [...result.nodes]).not.toThrow();
    expect(() => [...result.edges]).not.toThrow();
  });

  it("reports a body carrying neither array as an error, not an empty graph", () => {
    const result = normalizeGraph({ detail: "upstream failed" });
    expect(result.status).toBe("error");
    expect(result.detail).toBeTruthy();
  });

  it("does not claim an error when the server legitimately returned nothing", () => {
    const result = normalizeGraph({ nodes: [], edges: [], status: "empty" });
    expect(result.status).toBe("empty");
  });

  it("keeps a well-formed graph intact", () => {
    const result = normalizeGraph({ nodes: [goodNode], edges: [goodEdge] });
    expect(result.nodes).toEqual([goodNode]);
    expect(result.edges).toEqual([goodEdge]);
  });
});

describe("normalizeGraph — nodes that would throw downstream", () => {
  it.each([
    ["a null label", { ...goodNode, label: null }],
    ["a null type", { ...goodNode, type: null }],
    ["a numeric label", { ...goodNode, label: 42 }],
    ["a missing id", { label: "x", type: "PROPER", memories: 1 }],
    ["an empty id", { ...goodNode, id: "" }],
    ["a NaN memory count", { ...goodNode, memories: Number.NaN }],
    ["a string memory count", { ...goodNode, memories: "3" }],
    ["null itself", null],
    ["a string", "not a node"],
  ])("drops a node with %s", (_label, node) => {
    const result = normalizeGraph({ nodes: [node, goodNode], edges: [] });
    expect(result.nodes).toEqual([goodNode]);
  });

  it("leaves the surviving nodes safe to render", () => {
    // These two calls are the exact downstream throw paths the filter exists
    // to remove: n.type.toLowerCase() and n.label.length.
    const result = normalizeGraph({
      nodes: [{ ...goodNode, label: null }, goodNode],
      edges: [],
    });
    for (const node of result.nodes) {
      expect(() => node.type.toLowerCase()).not.toThrow();
      expect(() => node.label.length).not.toThrow();
    }
  });
});

describe("normalizeGraph — edges", () => {
  it.each([
    ["a missing source", { target: "n2", relationship: "x", weight: 1 }],
    [
      "a null target",
      { source: "n1", target: null, relationship: "x", weight: 1 },
    ],
    [
      "a non-numeric weight",
      { source: "n1", target: "n2", relationship: "x", weight: "2" },
    ],
    ["null", null],
  ])("drops an edge with %s", (_label, edge) => {
    const result = normalizeGraph({ nodes: [], edges: [edge, goodEdge] });
    expect(result.edges).toEqual([goodEdge]);
  });
});

describe("normalizeGraph — truncation metadata", () => {
  it("passes through what the server reported", () => {
    const result = normalizeGraph({
      nodes: [goodNode],
      edges: [],
      truncated: true,
      total_nodes: 500,
    });
    expect(result.truncated).toBe(true);
    expect(result.total_nodes).toBe(500);
  });

  it("falls back to the node count when the server did not say", () => {
    const result = normalizeGraph({ nodes: [goodNode], edges: [] });
    expect(result.truncated).toBe(false);
    expect(result.total_nodes).toBe(1);
  });
});

describe("pruneEdges", () => {
  it("drops edges whose endpoints are not both visible", () => {
    const edges = [
      { source: "a", target: "b", relationship: "x", weight: 1 },
      { source: "a", target: "gone", relationship: "x", weight: 1 },
    ];
    expect(pruneEdges(edges, new Set(["a", "b"]))).toHaveLength(1);
  });

  it("returns nothing when nothing is visible", () => {
    const edges = [{ source: "a", target: "b", relationship: "x", weight: 1 }];
    expect(pruneEdges(edges, new Set())).toEqual([]);
  });
});
