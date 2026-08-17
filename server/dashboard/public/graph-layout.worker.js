/**
 * Force-directed graph layout, off the main thread.
 *
 * The previous implementation ran an all-pairs simulation for 320 ticks
 * synchronously inside a React render. That is O(n²) per tick with the tab
 * frozen for the duration — the reason the graph page was unusable past about
 * 150 nodes.
 *
 * Two changes fix it. The repulsion pass uses a Barnes–Hut quadtree, which
 * approximates distant clusters as a single mass and turns O(n²) into
 * O(n log n). And the whole thing runs in a worker, posting positions back as
 * it settles, so the main thread stays responsive and the layout is visible
 * while it happens rather than after.
 *
 * Plain JS in /public rather than a bundled module: workers instantiated from a
 * bundler URL need build configuration that varies by Next version, and this
 * file has no imports to bundle.
 */

const THETA = 0.9; // Barnes–Hut accuracy. Higher = faster, cruder.
const REPULSION = 900;
const SPRING = 0.02;
const SPRING_LENGTH = 60;
const CENTER_PULL = 0.0015;
const DAMPING = 0.86;
const MAX_VELOCITY = 12;

/** A quadtree node: either a leaf holding one body, or four children. */
function makeQuad(x, y, size) {
  return { x, y, size, mass: 0, cx: 0, cy: 0, body: null, children: null };
}

function insert(quad, body) {
  if (quad.body === null && quad.children === null) {
    quad.body = body;
    quad.mass = 1;
    quad.cx = body.x;
    quad.cy = body.y;
    return;
  }

  if (quad.children === null) {
    // Split, and push the existing body down before adding the new one.
    const half = quad.size / 2;
    quad.children = [
      makeQuad(quad.x, quad.y, half),
      makeQuad(quad.x + half, quad.y, half),
      makeQuad(quad.x, quad.y + half, half),
      makeQuad(quad.x + half, quad.y + half, half),
    ];
    const existing = quad.body;
    quad.body = null;
    if (existing) insert(quad, existing);
  }

  // Running centre of mass, so an internal node can stand in for its subtree.
  quad.cx = (quad.cx * quad.mass + body.x) / (quad.mass + 1);
  quad.cy = (quad.cy * quad.mass + body.y) / (quad.mass + 1);
  quad.mass += 1;

  const half = quad.size / 2;
  const index = (body.x >= quad.x + half ? 1 : 0) + (body.y >= quad.y + half ? 2 : 0);
  // A degenerate quad (many bodies at identical coordinates) would recurse
  // forever; stop subdividing once the cell is smaller than a pixel.
  if (quad.size > 1) insert(quad.children[index], body);
}

function applyRepulsion(quad, body, forces) {
  if (quad.mass === 0) return;
  if (quad.body === body) return;

  let dx = quad.cx - body.x;
  let dy = quad.cy - body.y;
  let distanceSq = dx * dx + dy * dy;

  if (distanceSq < 0.01) {
    // Coincident bodies get a deterministic nudge rather than a random one, so
    // the layout is reproducible for the same input.
    dx = (body.index % 7) - 3;
    dy = (body.index % 5) - 2;
    distanceSq = dx * dx + dy * dy || 1;
  }

  const distance = Math.sqrt(distanceSq);

  // The Barnes–Hut test: if this cell is far enough away relative to its size,
  // treat the whole subtree as one mass instead of descending into it.
  if (quad.children === null || quad.size / distance < THETA) {
    const force = (-REPULSION * quad.mass) / distanceSq;
    forces.fx += (dx / distance) * force;
    forces.fy += (dy / distance) * force;
    return;
  }

  for (const child of quad.children) applyRepulsion(child, body, forces);
}

function step(bodies, edges) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const body of bodies) {
    if (body.x < minX) minX = body.x;
    if (body.y < minY) minY = body.y;
    if (body.x > maxX) maxX = body.x;
    if (body.y > maxY) maxY = body.y;
  }
  const size = Math.max(maxX - minX, maxY - minY, 1) * 2;
  const root = makeQuad(minX - size / 4, minY - size / 4, size);
  for (const body of bodies) insert(root, body);

  for (const body of bodies) {
    const forces = { fx: 0, fy: 0 };
    applyRepulsion(root, body, forces);
    // Everything drifts toward the centre, so disconnected components do not
    // fly apart forever.
    forces.fx += -body.x * CENTER_PULL * bodies.length;
    forces.fy += -body.y * CENTER_PULL * bodies.length;
    body.fx = forces.fx;
    body.fy = forces.fy;
  }

  for (const edge of edges) {
    const a = bodies[edge.s];
    const b = bodies[edge.t];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const distance = Math.sqrt(dx * dx + dy * dy) || 1;
    // Heavier edges pull harder, but only logarithmically - a weight-50 edge
    // should not collapse onto itself.
    const strength = SPRING * (1 + Math.log1p(edge.w));
    const force = (distance - SPRING_LENGTH) * strength;
    const nx = (dx / distance) * force;
    const ny = (dy / distance) * force;
    a.fx += nx;
    a.fy += ny;
    b.fx -= nx;
    b.fy -= ny;
  }

  let movement = 0;
  for (const body of bodies) {
    if (body.pinned) {
      body.vx = 0;
      body.vy = 0;
      continue;
    }
    body.vx = (body.vx + body.fx) * DAMPING;
    body.vy = (body.vy + body.fy) * DAMPING;
    const speed = Math.hypot(body.vx, body.vy);
    if (speed > MAX_VELOCITY) {
      body.vx = (body.vx / speed) * MAX_VELOCITY;
      body.vy = (body.vy / speed) * MAX_VELOCITY;
    }
    body.x += body.vx;
    body.y += body.vy;
    movement += Math.abs(body.vx) + Math.abs(body.vy);
  }
  return movement / (bodies.length || 1);
}

let current = null;

self.onmessage = (event) => {
  const message = event.data || {};

  if (message.type === "layout") {
    const { nodes, edges, iterations = 300 } = message;

    // Seeded on a circle rather than at random: the same graph then lays out
    // the same way every time, which matters when someone reloads to compare.
    const bodies = nodes.map((node, index) => {
      const angle = (index / Math.max(1, nodes.length)) * Math.PI * 2;
      const radius = 60 + Math.sqrt(nodes.length) * 14;
      return {
        id: node.id,
        index,
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        fx: 0,
        fy: 0,
        pinned: false,
      };
    });

    const indexById = new Map(bodies.map((b, i) => [b.id, i]));
    const links = [];
    for (const edge of edges) {
      const s = indexById.get(edge.source);
      const t = indexById.get(edge.target);
      if (s !== undefined && t !== undefined && s !== t) {
        links.push({ s, t, w: edge.weight || 1 });
      }
    }

    current = { bodies, links, iteration: 0, iterations };
    run();
  }

  if (message.type === "pin" && current) {
    const body = current.bodies.find((b) => b.id === message.id);
    if (body) {
      body.pinned = message.pinned;
      if (message.x !== undefined) body.x = message.x;
      if (message.y !== undefined) body.y = message.y;
    }
  }

  if (message.type === "stop") {
    current = null;
  }
};

function run() {
  if (!current) return;
  const started = Date.now();

  // Work in slices bounded by wall-clock, not by iteration count. A slice of
  // "20 ticks" is instant on a small graph and half a second on a large one;
  // a slice of "12ms" is a frame either way, so positions keep flowing.
  while (current.iteration < current.iterations && Date.now() - started < 12) {
    const movement = step(current.bodies, current.links);
    current.iteration += 1;
    if (movement < 0.02 && current.iteration > 40) {
      // Settled. Stopping early is the difference between a graph that appears
      // and one that keeps jittering for no visible benefit.
      current.iteration = current.iterations;
      break;
    }
  }

  const positions = new Float32Array(current.bodies.length * 2);
  for (let i = 0; i < current.bodies.length; i += 1) {
    positions[i * 2] = current.bodies[i].x;
    positions[i * 2 + 1] = current.bodies[i].y;
  }

  const done = current.iteration >= current.iterations;
  self.postMessage(
    { type: "positions", positions, progress: current.iteration / current.iterations, done },
    [positions.buffer],
  );

  if (!done) setTimeout(run, 0);
}
