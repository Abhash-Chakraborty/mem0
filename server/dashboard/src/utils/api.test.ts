/**
 * The refresh path, which is where a working login used to come apart.
 *
 * Refresh tokens rotate and are single-use. Two requests that refresh at the
 * same time therefore present the same cookie, the server spends it once, and
 * the loser's 401 destroys a session that was valid — so a correct password
 * signed the user in and then bounced them straight back to /login. These tests
 * pin the two rules that stop that: refreshes coalesce, and a 401 from the
 * endpoints that *establish* a session is an answer rather than a stale token.
 *
 * Node environment, no DOM: `redirectToLogin` no-ops without a window, so the
 * paths under test are reachable without standing up jsdom.
 */

import { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type FetchMock = ReturnType<typeof vi.fn>;

/** Re-import the module so its refresh-in-flight state starts empty each test. */
async function freshApi() {
  vi.resetModules();
  return import("./api");
}

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => body,
  } as Response;
}

/** A fetch that resolves only when the returned `release` is called. */
function deferredFetch(body: unknown) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fetchMock = vi.fn(async () => {
    await gate;
    return jsonResponse(body);
  });
  return { fetchMock, release };
}

let originalFetch: typeof globalThis.fetch;

beforeEach(() => {
  originalFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("refreshAccessToken", () => {
  it("coalesces concurrent callers onto a single request", async () => {
    const { fetchMock, release } = deferredFetch({ access_token: "token-1" });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { refreshAccessToken } = await freshApi();

    const pending = [
      refreshAccessToken(),
      refreshAccessToken(),
      refreshAccessToken(),
    ];
    release();
    const results = await Promise.all(pending);

    // The whole point: three callers, one spend of the single-use token.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(results).toEqual(["token-1", "token-1", "token-1"]);
  });

  it("posts to the cookie-backed route with credentials", async () => {
    const fetchMock: FetchMock = vi.fn(async () =>
      jsonResponse({ access_token: "token-1" }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { refreshAccessToken } = await freshApi();

    await refreshAccessToken();

    expect(fetchMock).toHaveBeenCalledWith("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    });
  });

  it("publishes the refreshed token to subsequent requests", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse({ access_token: "token-1" }),
    ) as unknown as typeof fetch;
    const { refreshAccessToken, getAccessToken } = await freshApi();

    await refreshAccessToken();

    expect(getAccessToken()).toBe("token-1");
  });

  it("starts a new request once the previous one has settled", async () => {
    const fetchMock: FetchMock = vi.fn(async () =>
      jsonResponse({ access_token: "token-1" }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { refreshAccessToken } = await freshApi();

    await refreshAccessToken();
    await refreshAccessToken();

    // Coalescing must not curdle into caching: an access token expires, and a
    // later refresh has to actually reach the server.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("resolves null on a rejected refresh", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse({ error: "No refresh token" }, false, 401),
    ) as unknown as typeof fetch;
    const { refreshAccessToken } = await freshApi();

    await expect(refreshAccessToken()).resolves.toBeNull();
  });

  it("resolves null rather than throwing when the network fails", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    const { refreshAccessToken } = await freshApi();

    await expect(refreshAccessToken()).resolves.toBeNull();
  });

  it("recovers after a failure instead of latching onto it", async () => {
    let attempt = 0;
    globalThis.fetch = vi.fn(async () => {
      attempt += 1;
      if (attempt === 1) throw new TypeError("Failed to fetch");
      return jsonResponse({ access_token: "token-2" });
    }) as unknown as typeof fetch;
    const { refreshAccessToken } = await freshApi();

    await expect(refreshAccessToken()).resolves.toBeNull();
    await expect(refreshAccessToken()).resolves.toBe("token-2");
  });
});

/** Make the shared instance fail one request with `status`, without a server. */
function stubAdapter(api: { defaults: { adapter?: unknown } }, status: number) {
  api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const response = {
      data: { detail: "Invalid email or password." },
      status,
      statusText: "",
      headers: {},
      config,
    } as AxiosResponse;
    throw new AxiosError(
      "Request failed",
      "ERR_BAD_REQUEST",
      config,
      {},
      response,
    );
  };
}

describe("401 handling", () => {
  it("does not refresh when the login request itself is rejected", async () => {
    const fetchMock: FetchMock = vi.fn(async () =>
      jsonResponse({ access_token: "token-1" }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { api } = await freshApi();
    stubAdapter(api, 401);

    await expect(api.post("/auth/login", {})).rejects.toBeDefined();

    // A wrong password is the server's answer, not a stale session. Refreshing
    // here spent a good token and redirected over the error the form was about
    // to show, so the page just silently reloaded.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces the server's reason for a rejected login", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse({ access_token: "token-1" }),
    ) as unknown as typeof fetch;
    const { api } = await freshApi();
    stubAdapter(api, 401);

    const error = await api.post("/auth/login", {}).catch((e) => e);

    expect(error.response?.data?.detail).toBe("Invalid email or password.");
  });

  it("does not refresh in response to a failing refresh", async () => {
    const fetchMock: FetchMock = vi.fn(async () =>
      jsonResponse({ access_token: "token-1" }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { api } = await freshApi();
    stubAdapter(api, 401);

    await expect(api.post("/auth/refresh", {})).rejects.toBeDefined();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refreshes once and retries a data request that 401s", async () => {
    const fetchMock: FetchMock = vi.fn(async () =>
      jsonResponse({ access_token: "token-1" }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { api } = await freshApi();

    let calls = 0;
    api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      calls += 1;
      if (calls === 1) {
        const response = {
          data: {},
          status: 401,
          statusText: "",
          headers: {},
          config,
        } as AxiosResponse;
        throw new AxiosError(
          "Unauthorized",
          "ERR_BAD_REQUEST",
          config,
          {},
          response,
        );
      }
      return {
        data: { ok: true },
        status: 200,
        statusText: "OK",
        headers: {},
        config,
      } as AxiosResponse;
    };

    const response = await api.get("/scope");

    expect(response.data).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(calls).toBe(2);
  });

  it("gives up after one retry instead of looping", async () => {
    const fetchMock: FetchMock = vi.fn(async () =>
      jsonResponse({ access_token: "token-1" }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { api } = await freshApi();

    let calls = 0;
    api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      calls += 1;
      const response = {
        data: {},
        status: 401,
        statusText: "",
        headers: {},
        config,
      } as AxiosResponse;
      throw new AxiosError(
        "Unauthorized",
        "ERR_BAD_REQUEST",
        config,
        {},
        response,
      );
    };

    await expect(api.get("/scope")).rejects.toBeDefined();

    // A token the server keeps refusing must not drive refresh/retry forever.
    expect(calls).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears the cached token when the session cannot be refreshed", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse({ error: "No refresh token" }, false, 401),
    ) as unknown as typeof fetch;
    const { api, setAccessToken, getAccessToken } = await freshApi();
    setAccessToken("stale-token");
    stubAdapter(api, 401);

    await expect(api.get("/scope")).rejects.toBeDefined();

    expect(getAccessToken()).toBeNull();
  });

  it("leaves non-401 failures alone", async () => {
    const fetchMock: FetchMock = vi.fn(async () =>
      jsonResponse({ access_token: "token-1" }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { api } = await freshApi();
    stubAdapter(api, 403);

    await expect(api.get("/orgs")).rejects.toBeDefined();

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
