"use client";

/**
 * The active organization and project.
 *
 * Scope is deliberately not a route parameter. Every page would have to carry
 * it, every link would have to rebuild it, and a page that forgot would read
 * the default project while showing another project's name in the switcher.
 * Instead the choice lives here, is mirrored into the axios interceptor so it
 * rides on every request, and is persisted per browser so a reload does not
 * silently drop the user back into the default project.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api, setActiveScope } from "@/utils/api";
import { TENANCY_ENDPOINTS } from "@/utils/api-endpoints";
import { useAuth } from "@/hooks/use-auth";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  role: string;
  project_count: number;
  member_count: number;
  created_at: string;
}

export interface Project {
  id: string;
  org_id: string;
  name: string;
  slug: string;
  description: string;
  settings: Record<string, unknown>;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface ResolvedScope {
  org_id: string;
  org_name: string;
  org_slug: string;
  project_id: string;
  project_name: string;
  project_slug: string;
  role: string;
  is_default_project: boolean;
}

/** Ranks mirror the server's, so the UI hides what the API would refuse. */
export const ROLE_RANK: Record<string, number> = {
  reader: 10,
  member: 20,
  admin: 30,
  owner: 40,
};

export function rankOf(role: string | undefined): number {
  return ROLE_RANK[role ?? ""] ?? 0;
}

interface ScopeContextValue {
  scope: ResolvedScope | null;
  orgs: Organization[];
  projects: Project[];
  isLoading: boolean;
  error: string | null;
  /** True when the caller's role on the current project meets `minimum`. */
  can: (minimum: string) => boolean;
  switchOrg: (orgId: string) => void;
  switchProject: (projectId: string) => void;
  reload: () => Promise<void>;
}

const ScopeContext = createContext<ScopeContextValue>({
  scope: null,
  orgs: [],
  projects: [],
  isLoading: true,
  error: null,
  can: () => false,
  switchOrg: () => {},
  switchProject: () => {},
  reload: async () => {},
});

const ORG_STORAGE_KEY = "mem0.scope.org";
const PROJECT_STORAGE_KEY = "mem0.scope.project";

function readStored(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    // Private-mode browsers throw on localStorage. Falling back to the default
    // scope is correct; failing to render the dashboard is not.
    return null;
  }
}

function writeStored(key: string, value: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* see readStored */
  }
}

export function ScopeProvider({ children }: { children: React.ReactNode }) {
  const { user, isLoading: isAuthLoading } = useAuth();
  const [scope, setScope] = useState<ResolvedScope | null>(null);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Selection is held in a ref as well as in the interceptor because a switch
  // has to take effect on the very next request, before React has re-rendered.
  const selection = useRef<{ org: string | null; project: string | null }>({
    org: null,
    project: null,
  });

  const load = useCallback(async () => {
    setError(null);
    try {
      const resolved = await api.get<ResolvedScope>(TENANCY_ENDPOINTS.SCOPE);
      setScope(resolved.data);

      // The server is the authority on what the headers resolved to. Writing
      // its answer back means a stale stored id (deleted project, revoked
      // membership) self-heals on the next load instead of 404ing forever.
      selection.current = {
        org: resolved.data.org_id,
        project: resolved.data.project_id,
      };
      setActiveScope(resolved.data.org_id, resolved.data.project_id);
      writeStored(ORG_STORAGE_KEY, resolved.data.org_id);
      writeStored(PROJECT_STORAGE_KEY, resolved.data.project_id);

      const [orgList, projectList] = await Promise.all([
        api.get<Organization[]>(TENANCY_ENDPOINTS.ORGS),
        api.get<Project[]>(TENANCY_ENDPOINTS.PROJECTS),
      ]);
      setOrgs(orgList.data);
      setProjects(projectList.data);
    } catch {
      setError("Could not load your organizations and projects.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  // The stored selection is adopted immediately so that the first request to
  // leave this provider already carries the right headers. It costs nothing:
  // reading localStorage is not a request.
  useEffect(() => {
    const storedOrg = readStored(ORG_STORAGE_KEY);
    const storedProject = readStored(PROJECT_STORAGE_KEY);
    selection.current = { org: storedOrg, project: storedProject };
    setActiveScope(storedOrg, storedProject);
  }, []);

  // Fetching waits for the session. /scope needs a bearer token, and this
  // provider mounts in the same commit as the auth bootstrap that obtains one,
  // so loading unconditionally would 401 on every dashboard load — and the
  // retry behind that 401 would race the bootstrap for a single-use refresh
  // token. Whichever lost took the whole session down with it, which is why a
  // correct password could still land the user back on /login.
  const userId = user?.id ?? null;
  useEffect(() => {
    if (isAuthLoading) return;
    if (!userId) {
      setIsLoading(false);
      return;
    }
    void load();
  }, [isAuthLoading, userId, load]);

  const switchOrg = useCallback(
    (orgId: string) => {
      // The project is cleared, not carried over: project ids are scoped to an
      // org, so keeping one across a switch would ask for a project that org
      // does not have. Clearing it lands on the new org's default.
      selection.current = { org: orgId, project: null };
      setActiveScope(orgId, null);
      writeStored(ORG_STORAGE_KEY, orgId);
      writeStored(PROJECT_STORAGE_KEY, null);
      setIsLoading(true);
      void load();
    },
    [load],
  );

  const switchProject = useCallback(
    (projectId: string) => {
      selection.current = { ...selection.current, project: projectId };
      setActiveScope(selection.current.org, projectId);
      writeStored(PROJECT_STORAGE_KEY, projectId);
      setIsLoading(true);
      void load();
    },
    [load],
  );

  const can = useCallback(
    (minimum: string) => rankOf(scope?.role) >= rankOf(minimum),
    [scope?.role],
  );

  const value = useMemo<ScopeContextValue>(
    () => ({
      scope,
      orgs,
      projects,
      isLoading,
      error,
      can,
      switchOrg,
      switchProject,
      reload: load,
    }),
    [
      scope,
      orgs,
      projects,
      isLoading,
      error,
      can,
      switchOrg,
      switchProject,
      load,
    ],
  );

  return (
    <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>
  );
}

export function useScope() {
  return useContext(ScopeContext);
}
