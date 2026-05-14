/**
 * API Client
 * ===========
 * Centralized Axios instance with:
 * - Base URL from environment
 * - Request interceptors (auth token injection, request ID)
 * - Response interceptors (error normalization)
 * - Typed response envelope unwrapping
 */

import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
} from "axios";

// ── Types ───────────────────────────────────────────────────

export interface APISuccessResponse<T> {
  success: true;
  data: T;
  meta?: PaginationMeta;
  message?: string;
  request_id: string;
}

export interface APIErrorResponse {
  success: false;
  error: {
    code: string;
    message: string;
    detail?: unknown;
  };
  request_id: string;
}

export interface PaginationMeta {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export class APIError extends Error {
  constructor(
    public code: string,
    message: string,
    public detail?: unknown,
    public requestId?: string,
    public status?: number
  ) {
    super(message);
    this.name = "APIError";
  }
}

// ── Client Factory ──────────────────────────────────────────

function createAPIClient(): AxiosInstance {
  const client = axios.create({
    baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1",
    timeout: 30_000,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
  });

  // ── Request Interceptor ──────────────────────────────────
  client.interceptors.request.use(
    (config) => {
      // Inject auth token (Phase 2 will populate this)
      const token = localStorage.getItem("access_token");
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }

      // Unique request ID for tracing
      config.headers["X-Request-ID"] = crypto.randomUUID();

      return config;
    },
    (error) => Promise.reject(error)
  );

  // ── Response Interceptor ─────────────────────────────────
  client.interceptors.response.use(
    (response: AxiosResponse<APISuccessResponse<unknown>>) => response,
    (error) => {
      if (axios.isAxiosError(error) && error.response) {
        const body = error.response.data as APIErrorResponse;
        throw new APIError(
          body?.error?.code || "UNKNOWN_ERROR",
          body?.error?.message || error.message,
          body?.error?.detail,
          body?.request_id,
          error.response.status
        );
      }

      if (axios.isAxiosError(error) && error.code === "ECONNABORTED") {
        throw new APIError("TIMEOUT", "Request timed out. Please try again.");
      }

      throw new APIError("NETWORK_ERROR", "Network error. Check your connection.");
    }
  );

  return client;
}

export const apiClient: AxiosInstance = createAPIClient();

// ── Convenience Methods (typed, envelope-unwrapping) ────────

export async function apiGet<T>(
  url: string,
  config?: AxiosRequestConfig
): Promise<APISuccessResponse<T>> {
  const response = await apiClient.get<APISuccessResponse<T>>(url, config);
  return response.data;
}

export async function apiPost<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<APISuccessResponse<T>> {
  const response = await apiClient.post<APISuccessResponse<T>>(url, data, config);
  return response.data;
}

export async function apiPut<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<APISuccessResponse<T>> {
  const response = await apiClient.put<APISuccessResponse<T>>(url, data, config);
  return response.data;
}

export async function apiPatch<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<APISuccessResponse<T>> {
  const response = await apiClient.patch<APISuccessResponse<T>>(url, data, config);
  return response.data;
}

export async function apiDelete<T = void>(
  url: string,
  config?: AxiosRequestConfig
): Promise<APISuccessResponse<T>> {
  const response = await apiClient.delete<APISuccessResponse<T>>(url, config);
  return response.data;
}
