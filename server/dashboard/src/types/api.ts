export interface Memory {
  id: string;
  memory: string;
  user_id?: string;
  agent_id?: string;
  run_id?: string;
  metadata?: Record<string, unknown>;
  categories?: MemoryCategory[];
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
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
  weight: number;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
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

export interface AnalyticsSummary {
  total_requests: number;
  success_rate: number;
  average_latency_ms: number;
  total_memories: number;
  categorized_memories: number;
  by_path: Array<{ path: string; count: number }>;
  by_status: Array<{ status: string; count: number }>;
  by_day: Array<{ date: string; count: number }>;
  category_distribution: Array<{ name: string; color: string; count: number }>;
  webhook_deliveries: Array<{ status: string; count: number }>;
}
