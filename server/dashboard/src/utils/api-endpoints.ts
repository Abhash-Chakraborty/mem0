export const AUTH_ENDPOINTS = {
  SETUP_STATUS: "/auth/setup-status",
  REGISTER: "/auth/register",
  LOGIN: "/auth/login",
  REFRESH: "/auth/refresh",
  ME: "/auth/me",
  CHANGE_PASSWORD: "/auth/change-password",
  ONBOARDING_COMPLETE: "/auth/onboarding-complete",
} as const;

export const MEMORY_ENDPOINTS = {
  BASE: "/memories",
  BY_ID: (memoryId: string) => `/memories/${memoryId}`,
  HISTORY: (memoryId: string) => `/memories/${memoryId}/history`,
  LIFECYCLE: (memoryId: string) => `/memories/${memoryId}/lifecycle`,
  FEEDBACK: (memoryId: string) => `/memories/${memoryId}/feedback`,
  CONFIGURE: "/configure",
  CONFIGURE_PROVIDERS: "/configure/providers",
  RESET: "/reset",
  GENERATE_INSTRUCTIONS: "/generate-instructions",
} as const;

export const TENANCY_ENDPOINTS = {
  SCOPE: "/scope",
  ORGS: "/orgs",
  ORG_BY_ID: (orgId: string) => `/orgs/${orgId}`,
  ORG_MEMBERS: (orgId: string) => `/orgs/${orgId}/members`,
  ORG_MEMBER: (orgId: string, memberId: string) =>
    `/orgs/${orgId}/members/${memberId}`,
  ORG_INVITES: (orgId: string) => `/orgs/${orgId}/invites`,
  ORG_INVITE: (orgId: string, inviteId: string) =>
    `/orgs/${orgId}/invites/${inviteId}`,
  ACCEPT_INVITE: "/invites/accept",
  PROJECTS: "/projects",
  PROJECT_BY_ID: (projectId: string) => `/projects/${projectId}`,
  PROJECT_MEMBERS: (projectId: string) => `/projects/${projectId}/members`,
  PROJECT_MEMBER: (projectId: string, memberId: string) =>
    `/projects/${projectId}/members/${memberId}`,
} as const;

export const API_KEY_ENDPOINTS = {
  BASE: "/api-keys",
  BY_ID: (keyId: string) => `/api-keys/${keyId}`,
} as const;

export const REQUEST_ENDPOINTS = {
  BASE: "/requests",
  HISTOGRAM: "/requests/histogram",
  BY_ID: (requestId: string) => `/requests/${requestId}`,
} as const;

export const ENTITY_ENDPOINTS = {
  BASE: "/entities",
  BY_ID: (type: string, id: string) =>
    `/entities/${type}/${encodeURIComponent(id)}`,
  MEMORIES: (type: string, id: string) =>
    `/entities/${type}/${encodeURIComponent(id)}/memories`,
  REQUESTS: (type: string, id: string) =>
    `/entities/${type}/${encodeURIComponent(id)}/requests`,
  PROFILE: (type: string, id: string) =>
    `/entities/${type}/${encodeURIComponent(id)}/profile`,
  LINKS: "/entities/links",
  LINK_BY_ID: (linkId: string) => `/entities/links/${linkId}`,
  MERGE: "/entities/merge",
} as const;

export const DREAM_ENDPOINTS = {
  STATUS: "/dream/status",
  RUNS: "/dream/runs",
  ACTIONS: "/dream/actions",
  REVERT: (actionId: string) => `/dream/actions/${actionId}/revert`,
  SYNTHESIZE: "/dream/synthesize",
} as const;

export const GRAPH_ENDPOINTS = {
  BASE: "/graph",
  NEIGHBOURHOOD: (key: string) => `/graph/nodes/${encodeURIComponent(key)}`,
  REBUILD: "/graph/rebuild",
} as const;

export const CATEGORY_ENDPOINTS = {
  BASE: "/categories",
  MEMORIES: "/categories/memories",
  BY_ID: (categoryId: string) => `/categories/${categoryId}`,
  CLASSIFY_MEMORY: (memoryId: string) =>
    `/categories/memories/${memoryId}/classify`,
  ASSIGN_MEMORY: (memoryId: string) =>
    `/categories/memories/${memoryId}/assign`,
  UNASSIGN_MEMORY: (memoryId: string, categoryId: string) =>
    `/categories/memories/${memoryId}/assign/${categoryId}`,
  RECLASSIFY: "/categories/reclassify",
  AUTO_GENERATE: "/categories/auto-generate",
} as const;

export const WEBHOOK_ENDPOINTS = {
  BASE: "/webhooks",
  EVENTS: "/webhooks/events",
  BY_ID: (endpointId: string) => `/webhooks/${endpointId}`,
  REGENERATE_SECRET: (endpointId: string) =>
    `/webhooks/${endpointId}/regenerate-secret`,
  TEST: (endpointId: string) => `/webhooks/${endpointId}/test`,
  DELIVERIES: "/webhooks/deliveries",
  RETRY_DELIVERY: (deliveryId: string) =>
    `/webhooks/deliveries/${deliveryId}/retry`,
} as const;

export const ANALYTICS_ENDPOINTS = {
  BASE: "/analytics",
} as const;

export const EXPORT_ENDPOINTS = {
  BASE: "/export",
} as const;

export const BACKUP_ENDPOINTS = {
  BASE: "/backups",
  BY_ID: (backupId: string) => `/backups/${backupId}`,
  DOWNLOAD: (backupId: string, part: "vector" | "app") =>
    `/backups/${backupId}/download?part=${part}`,
  RESTORE: (backupId: string) => `/backups/${backupId}/restore`,
} as const;

export const SYSTEM_ENDPOINTS = {
  HEALTH: "/system/health",
  VERSION: "/system/version",
  LOGS: "/system/logs",
  LOG_STREAM: "/system/logs/stream",
} as const;

export const RECALL_ENDPOINTS = {
  SEARCH: "/search",
  HISTORY: (memoryId: string) => `/memories/${memoryId}/history`,
} as const;
