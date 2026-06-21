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
  CONFIGURE: "/configure",
  CONFIGURE_PROVIDERS: "/configure/providers",
  RESET: "/reset",
  GENERATE_INSTRUCTIONS: "/generate-instructions",
} as const;

export const API_KEY_ENDPOINTS = {
  BASE: "/api-keys",
  BY_ID: (keyId: string) => `/api-keys/${keyId}`,
} as const;

export const REQUEST_ENDPOINTS = {
  BASE: "/requests",
} as const;

export const ENTITY_ENDPOINTS = {
  BASE: "/entities",
  BY_ID: (type: string, id: string) =>
    `/entities/${type}/${encodeURIComponent(id)}`,
} as const;

export const GRAPH_ENDPOINTS = {
  BASE: "/graph",
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
} as const;

export const WEBHOOK_ENDPOINTS = {
  BASE: "/webhooks",
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
