import axios, {
  AxiosError,
  AxiosInstance,
  InternalAxiosRequestConfig,
} from "axios";

let cachedToken: string | null = null;
const LOGIN_PATH = "/login";

export const ORG_HEADER = "X-Mem0-Org";
export const PROJECT_HEADER = "X-Mem0-Project";

// Endpoints that establish a session rather than consume one. A 401 from these
// is the answer, not a stale-token symptom: bad credentials on /auth/login must
// surface to the form as "Invalid email or password", and refreshing or
// redirecting in response would replace that message with a page reload.
const SESSION_ENDPOINTS = ["/auth/login", "/auth/register", "/auth/refresh"];

// The active org/project ride on every request from here rather than being
// threaded through each caller. A page that forgot to pass them would silently
// read the default project instead of the one on screen, and nothing in the
// response would say so.
let activeOrg: string | null = null;
let activeProject: string | null = null;

export const setActiveScope = (org: string | null, project: string | null) => {
  activeOrg = org;
  activeProject = project;
};

export const getActiveScope = () => ({
  org: activeOrg,
  project: activeProject,
});

export const setAccessToken = (token: string | null) => {
  cachedToken = token;
};

export const getAccessToken = (): string | null => {
  return cachedToken;
};

const handleTokenError = () => {
  cachedToken = null;
};

const isSessionEndpoint = (url: string | undefined): boolean => {
  if (!url) return false;
  // Compared against the path only: callers pass relative paths, but an
  // absolute URL would still have to match on its pathname and not on a
  // query string that happens to mention /auth/login.
  const path = url.startsWith("http") ? new URL(url).pathname : url;
  return SESSION_ENDPOINTS.some((endpoint) => path.endsWith(endpoint));
};

const redirectToLogin = () => {
  if (typeof window === "undefined") return;
  // Already on the login page: reloading it would clear a half-typed form and,
  // worse, wipe the error the user is meant to read.
  if (window.location.pathname === LOGIN_PATH) return;

  const next = window.location.pathname + window.location.search;
  window.location.href = `${LOGIN_PATH}?next=${encodeURIComponent(next)}`;
};

/**
 * The single refresh in flight, or null when none is.
 *
 * Refresh tokens rotate: the server consumes the presented token's jti and
 * issues a new one, so the same token can only be spent once. Two requests
 * refreshing concurrently therefore both present the same cookie, one wins,
 * and the loser's 401 tears down a session that was perfectly valid — which is
 * what happens on every dashboard load, where the auth bootstrap and the first
 * data fetches race each other. Coalescing onto one promise means N callers
 * spend the token once and all read the same answer.
 */
let inFlightRefresh: Promise<string | null> | null = null;

const performRefresh = async (): Promise<string | null> => {
  try {
    const response = await fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    });

    if (!response.ok) {
      return null;
    }

    const data = await response.json();
    setAccessToken(data.access_token);
    return data.access_token as string;
  } catch {
    // Network failure, not an invalid session. The caller treats null as
    // "no token"; the cookie is left alone so a blip does not sign the user out.
    return null;
  }
};

export const refreshAccessToken = (): Promise<string | null> => {
  if (!inFlightRefresh) {
    inFlightRefresh = performRefresh().finally(() => {
      inFlightRefresh = null;
    });
  }
  return inFlightRefresh;
};

/** Config carrying the marker that stops a retried request from retrying again. */
type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean };

const createApi = (): AxiosInstance => {
  const api = axios.create({
    baseURL: process.env.NEXT_PUBLIC_API_URL,
  });

  api.interceptors.request.use(
    async (config) => {
      if (cachedToken) {
        config.headers = config.headers ?? {};
        config.headers.Authorization = `Bearer ${cachedToken}`;
      }
      if (activeOrg || activeProject) {
        config.headers = config.headers ?? {};
        if (activeOrg) config.headers[ORG_HEADER] = activeOrg;
        if (activeProject) config.headers[PROJECT_HEADER] = activeProject;
      }
      return config;
    },
    (error) => {
      return Promise.reject(error);
    },
  );

  api.interceptors.response.use(
    (response) => response,
    async (error: AxiosError<{ error?: string }>) => {
      const config = error.config as RetriableConfig | undefined;

      // `_retried` bounds this to one attempt. Without it a token the server
      // keeps rejecting would refresh, retry, 401, refresh... indefinitely.
      const shouldAttemptRefresh =
        error.response?.status === 401 &&
        config !== undefined &&
        !config._retried &&
        !isSessionEndpoint(config.url);

      if (shouldAttemptRefresh && config) {
        handleTokenError();

        const nextToken = await refreshAccessToken();
        if (nextToken) {
          config._retried = true;
          config.headers = config.headers ?? {};
          config.headers.Authorization = `Bearer ${nextToken}`;
          return api.request(config);
        }

        handleTokenError();
        redirectToLogin();
      }

      if (error.response?.data?.error) {
        return Promise.reject(error.response.data.error);
      }

      return Promise.reject(error);
    },
  );

  return api;
};

export const api = createApi();
