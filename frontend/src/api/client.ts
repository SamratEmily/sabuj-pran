import axios, { AxiosError } from 'axios';

const TOKEN_KEY = 'bms_token';

export const tokenStorage = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string): void {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      // storage unavailable (private mode); the session just won't persist
    }
  },
  clear(): void {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      // ignore
    }
  },
};

/** Error body returned by the backend for every failure. */
export interface ApiErrorBody {
  detail: string;
  code: string;
  errors?: { loc: (string | number)[]; msg: string; type: string }[];
}

/** List response shape shared by every list endpoint. */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

let onUnauthorized: () => void = () => {
  tokenStorage.clear();
  window.location.assign('/login');
};

/** AuthProvider replaces the default (hard redirect) with a state-based logout. */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

api.interceptors.request.use((config) => {
  const token = tokenStorage.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    // A 401 from /auth/login is a wrong password, not an expired session.
    const isLogin = error.config?.url?.endsWith('/auth/login');
    if (error.response?.status === 401 && !isLogin && tokenStorage.get()) {
      onUnauthorized();
    }
    return Promise.reject(error);
  },
);

/** Human-readable message from any request error. */
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError<ApiErrorBody>(error)) {
    if (!error.response) return 'Cannot reach the server. Check your connection.';
    return error.response.data?.detail ?? error.message;
  }
  return error instanceof Error ? error.message : 'Unexpected error';
}

/** Backend error code (e.g. "PERMISSION_DENIED"), if any. */
export function errorCode(error: unknown): string | undefined {
  return axios.isAxiosError<ApiErrorBody>(error) ? error.response?.data?.code : undefined;
}

/** 422 field errors in Ant Design `form.setFields` format. */
export function fieldErrors(error: unknown): { name: (string | number)[]; errors: string[] }[] {
  if (!axios.isAxiosError<ApiErrorBody>(error)) return [];
  return (error.response?.data?.errors ?? [])
    .filter((e) => e.loc[0] === 'body' && e.loc.length > 1)
    .map((e) => ({ name: e.loc.slice(1), errors: [e.msg] }));
}
