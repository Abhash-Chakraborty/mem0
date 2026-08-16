import axios, { AxiosError, AxiosInstance } from "axios";

let cachedToken: string | null = null;
const LOGIN_PATH = "/login";

export const setAccessToken = (token: string | null) => {
  cachedToken = token;
};

export const getAccessToken = (): string | null => {
  return cachedToken;
};

const handleTokenError = () => {
  cachedToken = null;
};

const redirectToLogin = () => {
  if (typeof window !== "undefined") {
    window.location.href = LOGIN_PATH;
  }
};

const refreshAccessToken = async () => {
  const refreshResponse = await fetch("/api/auth/refresh", {
    method: "POST",
    credentials: "include",
  });

  if (!refreshResponse.ok) {
    return null;
  }

  const data = await refreshResponse.json();
  setAccessToken(data.access_token);
  return data.access_token as string;
};

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
      return config;
    },
    (error) => {
      return Promise.reject(error);
    },
  );

  api.interceptors.response.use(
    (response) => response,
    async (error: AxiosError<{ error?: string }>) => {
      if (error.response?.status === 401) {
        handleTokenError();

        try {
          const nextToken = await refreshAccessToken();
          if (nextToken && error.config) {
            error.config.headers = error.config.headers ?? {};
            error.config.headers.Authorization = `Bearer ${nextToken}`;
            return api.request(error.config);
          }
        } catch {}

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
