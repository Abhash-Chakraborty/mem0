/**
 * The typed search syntax, parsed client-side so filter chips can render
 * before the request is sent.
 *
 * Mirrors server/query_syntax.py. The server is the authority — it parses the
 * raw string again and never trusts what the client derived — but the box has
 * to show what it understood as you type, and a round trip per keystroke to
 * find that out would be its own problem.
 *
 * Unknown prefixes deliberately fall through to free text. `usr:alice` filtering
 * on nothing would silently return everything, and `https://x` would parse as a
 * `https:` filter.
 */

export const ENTITY_PREFIXES: Record<string, "user" | "agent" | "run"> = {
  user: "user",
  agent: "agent",
  run: "run",
  // The UI says Sessions and Apps where the API says run_id and agent_id.
  session: "run",
  app: "agent",
};

export const TYPE_VALUES = [
  "add",
  "search",
  "get_all",
  "get",
  "update",
  "delete",
  "delete_all",
  "other",
] as const;

export type RequestType = (typeof TYPE_VALUES)[number];

const TYPE_ALIASES: Record<string, RequestType> = {
  getall: "get_all",
  "get-all": "get_all",
  list: "get_all",
  deleteall: "delete_all",
  "delete-all": "delete_all",
  create: "add",
  write: "add",
  query: "search",
};

const STATUS_SYNONYMS: Record<string, "succeeded" | "failed"> = {
  succeeded: "succeeded",
  ok: "succeeded",
  success: "succeeded",
  "2xx": "succeeded",
  failed: "failed",
  error: "failed",
  fail: "failed",
  "4xx": "failed",
  "5xx": "failed",
};

const METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);

export interface ParsedQuery {
  types: RequestType[];
  status?: "succeeded" | "failed";
  entityType?: "user" | "agent" | "run";
  entityId?: string;
  method?: string;
  text?: string;
}

export const EMPTY_QUERY: ParsedQuery = { types: [] };

/** Split on whitespace, honouring quotes so `user:"ada lovelace"` survives. */
function tokenize(raw: string): string[] {
  const tokens: string[] = [];
  let current = "";
  let quote: string | null = null;

  for (const char of raw) {
    if (quote) {
      if (char === quote) quote = null;
      else current += char;
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (/\s/.test(char)) {
      if (current) tokens.push(current);
      current = "";
      continue;
    }
    current += char;
  }
  if (current) tokens.push(current);
  return tokens;
}

export function parseQuery(raw: string | undefined | null): ParsedQuery {
  if (!raw || !raw.trim()) return EMPTY_QUERY;

  const parsed: ParsedQuery = { types: [] };
  const free: string[] = [];

  for (const token of tokenize(raw)) {
    const match = /^([a-zA-Z_-]+):(.*)$/.exec(token);
    const value = match?.[2]?.trim();
    if (!match || !value) {
      free.push(token);
      continue;
    }
    const key = match[1].toLowerCase();

    if (key in ENTITY_PREFIXES) {
      parsed.entityType = ENTITY_PREFIXES[key];
      parsed.entityId = value;
    } else if (key === "type") {
      const normalized = (TYPE_ALIASES[value.toLowerCase()] ??
        value.toLowerCase()) as RequestType;
      if ((TYPE_VALUES as readonly string[]).includes(normalized)) {
        parsed.types.push(normalized);
      } else {
        free.push(token);
      }
    } else if (key === "status") {
      const normalized = STATUS_SYNONYMS[value.toLowerCase()];
      if (normalized) parsed.status = normalized;
      else free.push(token);
    } else if (key === "method") {
      const upper = value.toUpperCase();
      if (METHODS.has(upper)) parsed.method = upper;
      else free.push(token);
    } else {
      free.push(token);
    }
  }

  if (free.length) parsed.text = free.join(" ");
  return parsed;
}

/** Human-readable chips for what the query resolved to. */
export function describeQuery(parsed: ParsedQuery): string[] {
  const chips: string[] = [];
  for (const type of parsed.types) chips.push(`type: ${type}`);
  if (parsed.status) chips.push(`status: ${parsed.status}`);
  if (parsed.entityId) chips.push(`${parsed.entityType}: ${parsed.entityId}`);
  if (parsed.method) chips.push(`method: ${parsed.method}`);
  if (parsed.text) chips.push(`text: ${parsed.text}`);
  return chips;
}

export const QUERY_HINTS = [
  "user:alice",
  "agent:aurion",
  "session:s-42",
  "type:add",
  "type:search",
  "status:failed",
  "method:post",
];
