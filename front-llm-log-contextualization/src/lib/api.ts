import { ApiError, JobStatusResponse, JobSubmissionResponse } from "./types";

function resolveApiUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (fromEnv) {
    const normalized = fromEnv.replace(/\/$/, "");
    return normalized.replace("://localhost:", "://127.0.0.1:");
  }
  if (typeof window !== "undefined") {
    const host = window.location.hostname === "localhost" ? "127.0.0.1" : window.location.hostname;
    return `${window.location.protocol}//${host}:8000`;
  }
  return "http://127.0.0.1:8000";
}

const API_URL = resolveApiUrl();
const REQUEST_TIMEOUT_MS = 20_000;

function formatApiError(errBody: ApiError): string {
  return errBody.message || errBody.detail || errBody.error || "Request failed";
}

async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeoutMs: number = REQUEST_TIMEOUT_MS
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s. Backend may be unreachable at ${API_URL}.`
      );
    }
    throw new Error(`Network error while contacting backend at ${API_URL}.`);
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function submitAnalysis(
  file: File,
  options?: { forceRefresh?: boolean }
): Promise<JobSubmissionResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (options?.forceRefresh) {
    formData.append("force_refresh", "true");
  }

  const endpoint = new URL(`${API_URL}/api/analyze`);
  if (options?.forceRefresh) {
    endpoint.searchParams.set("force_refresh", "true");
  }

  const headers: HeadersInit = {};
  if (options?.forceRefresh) {
    headers["x-force-refresh"] = "1";
  }

  const res = await fetchWithTimeout(endpoint.toString(), {
    method: "POST",
    headers,
    body: formData,
  });

  if (!res.ok) {
    let errBody: ApiError = {};
    try {
      const parsed = await res.json();
      errBody = parsed?.detail || parsed;
    } catch {
      throw new Error(`Server error: ${res.status} ${res.statusText}`);
    }
    throw new Error(formatApiError(errBody));
  }

  return res.json();
}

export async function fetchJobStatus(jobId: string): Promise<JobStatusResponse> {
  const res = await fetchWithTimeout(`${API_URL}/api/jobs/${jobId}`, {
    method: "GET",
    cache: "no-store",
  });

  if (!res.ok) {
    let errBody: ApiError = {};
    try {
      const parsed = await res.json();
      errBody = parsed?.detail || parsed;
    } catch {
      throw new Error(`Server error: ${res.status} ${res.statusText}`);
    }
    throw new Error(formatApiError(errBody));
  }

  return res.json();
}
