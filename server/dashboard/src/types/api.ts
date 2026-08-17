/**
 * What has happened to a memory beyond existing.
 *
 * Always present on a memory from the API, even when nothing has happened —
 * the server fills in `active` rather than omitting the key, so the client
 * never has to tell "active" from "we did not look".
 */
export interface MemoryLifecycle {
  state: "active" | "superseded" | "merged" | "pattern" | "expired";
  superseded_by: string | null;
  merged_into: string | null;
  reason: string | null;
  actor: string | null;
  changed_at: string | null;
}

export interface MemoryAccess {
  count: number;
  last_access_at: string | null;
  first_access_at: string | null;
}

export interface Memory {
  id: string;
  memory: string;
  user_id?: string;
  agent_id?: string;
  run_id?: string;
  metadata?: Record<string, unknown>;
  categories?: MemoryCategory[];
  lifecycle?: MemoryLifecycle;
  /** Only returned when fetching a single memory. */
  access?: MemoryAccess;
  created_at?: string;
  updated_at?: string;
}

export interface ApiKey {
  id: string;
  label: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreateResponse {
  id: string;
  label: string;
  key: string;
  key_prefix: string;
  created_at: string;
}

export interface ApiRequestLog {
  id: string;
  created_at: string;
  method: string;
  path: string;
  status_code: number;
  latency_ms: number;
  auth_type: string;
}

export type EntityType = "user" | "agent" | "run" | "app";

export interface Entity {
  id: string;
  type: EntityType;
  total_memories: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  memories: number;
  /** Precomputed server-side; absent on responses from older server builds. */
  degree?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
  weight: number;
}

export type GraphStatus = "ok" | "empty" | "extractor_unavailable" | "error";

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  // Diagnostics from the backend so the UI can distinguish a genuinely empty
  // graph from a misconfigured one. Optional for backward compatibility with
  // older server builds that did not return them.
  status?: GraphStatus;
  detail?: string | null;
  source?: string;
  entity_extraction_available?: boolean;
  /** True when the server had more nodes than it returned. */
  truncated?: boolean;
  /** How many nodes exist in total, so the UI can say what is missing. */
  total_nodes?: number;
}

export interface Category {
  id: string;
  name: string;
  description: string;
  color: string;
  is_active: boolean;
  auto_add: boolean;
  memory_count: number;
  created_at: string;
  updated_at: string;
}

export interface MemoryCategory {
  id: string;
  category_id: string;
  name: string;
  color: string;
  confidence: number | null;
  reason: string;
  source: "ai" | "manual" | "auto";
  created_at: string;
  updated_at: string;
}

export interface WebhookEndpoint {
  id: string;
  name: string;
  url: string;
  events: string[];
  /** Payload shape on the wire. Absent on rows created before channels existed. */
  channel?: "generic" | "discord" | "slack";
  is_active: boolean;
  secret?: string;
  created_at: string;
  updated_at: string;
}

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  event_type: string;
  status: string;
  attempts: number;
  next_attempt_at: string | null;
  last_attempt_at: string | null;
  response_status: number | null;
  response_body: string;
  created_at: string;
}

export interface DashboardSeriesPoint {
  date: string;
  requests: number;
  adds: number;
  retrievals: number;
}

export interface AnalyticsSummary {
  total_memories: number;
  memories_in_range: number;
  total_requests: number;
  add_events: number;
  retrieval_events: number;
  success_rate: number;
  average_latency_ms: number;
  entities_total: number;
  entities_by_type: { user: number; agent: number; run: number; app: number };
  entities_per_request: number;
  series: DashboardSeriesPoint[];
  range: string;
  start: string | null;
  end: string | null;
  categorized_memories: number;
  category_distribution: Array<{ name: string; color: string; count: number }>;
}

export type HealthStatus =
  | "ok"
  | "degraded"
  | "critical"
  | "unavailable"
  | "unknown";

export interface Backup {
  id: string;
  filename: string;
  kind: string;
  status: "running" | "completed" | "failed";
  size_bytes: number;
  checksum: string;
  destination: string;
  error: string;
  started_at: string | null;
  completed_at: string | null;
  verified_at: string | null;
}

export interface BackupListResponse {
  backups: Backup[];
  retention_count: number;
  missing_tools: string[];
  directory: string;
}

/** Each health section reports its own status; extra keys vary by section. */
export interface HealthSection {
  status: HealthStatus;
  error?: string;
  [key: string]: unknown;
}

export interface SystemHealth {
  status: HealthStatus;
  uptime_seconds: number;
  generated_at: string;
  sections: Record<string, HealthSection>;
}

export interface LogEntry {
  timestamp: string;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  logger: string;
  message: string;
  request_id: string | null;
  error: string | null;
}

export interface LogListResponse {
  logs: LogEntry[];
  buffer_size: number;
}

/** Per-result score breakdown, returned when a search is run with explain. */
export interface ScoreDetails {
  semantic_score: number;
  bm25_score: number;
  entity_boost: number;
  raw_score: number;
  max_possible_score: number;
  final_score: number;
  threshold: number;
}

export interface RecallResult {
  id: string;
  memory?: string;
  user_id?: string;
  agent_id?: string;
  run_id?: string;
  created_at?: string;
  updated_at?: string;
  metadata?: Record<string, unknown> | null;
  score?: number;
  score_details?: ScoreDetails;
}

export interface RecallResponse {
  results?: RecallResult[];
}

export interface MemoryHistoryEntry {
  id?: string | number;
  memory_id?: string;
  old_memory?: string | null;
  new_memory?: string | null;
  event?: string;
  created_at?: string;
  updated_at?: string;
}
