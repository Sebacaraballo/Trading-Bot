// Typed fetch wrappers for the Earnings Intelligence API.
// Base URL comes from VITE_API_URL, defaulting to the local FastAPI server.

import type { BacktestResults, Filing, FilingText, Signal, Stats } from "../types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`);
  } catch {
    throw new ApiError(
      0,
      `Cannot reach the API at ${BASE_URL}. Is the backend running? ` +
        `Start it with: uvicorn api.main:app --reload`,
    );
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // response had no JSON body — keep the status text
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

function withQuery(path: string, params: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") qs.set(key, String(value));
  }
  const query = qs.toString();
  return query ? `${path}?${query}` : path;
}

export function getStats(): Promise<Stats> {
  return request<Stats>("/api/stats");
}

export function getSignals(ticker?: string, limit = 50): Promise<Signal[]> {
  return request<Signal[]>(withQuery("/api/signals", { ticker, limit }));
}

export function getSignal(id: number): Promise<Signal> {
  return request<Signal>(`/api/signals/${id}`);
}

export function getFilings(ticker?: string, limit = 50): Promise<Filing[]> {
  return request<Filing[]>(withQuery("/api/filings", { ticker, limit }));
}

export function getFilingText(id: number): Promise<FilingText> {
  return request<FilingText>(`/api/filings/${id}/text`);
}

// Returns null (not an error) when no backtest has been run yet (404), so the
// page can show its "not run yet" placeholder.
export async function getLatestBacktest(): Promise<BacktestResults | null> {
  try {
    return await request<BacktestResults>("/api/backtest/latest");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export { ApiError };
