export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ApiError' }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } })
  let body: { data?: T; error?: { message?: string; details?: { location: string[]; message: string }[] } }
  try { body = await response.json() } catch { throw new ApiError('The API returned an unreadable response. Check that FastAPI is running on port 8000.', response.status) }
  if (!response.ok) {
    const details = body.error?.details?.map(item => `${item.location.join('.')}: ${item.message}`).join('; ')
    throw new ApiError(details || body.error?.message || `Request failed (${response.status})`, response.status)
  }
  if (!('data' in body)) throw new ApiError('The API response is missing its data envelope.', response.status)
  return body.data as T
}
export const get = <T,>(path: string, signal?: AbortSignal) => request<T>(path, { signal })
export const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
export function query(params: Record<string, string | number | undefined>) {
  return new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => [key, String(value)])).toString()
}
export const exportUrl = (dataset: string, format: string, runId?: string) => `/api/reports/export?${query({ dataset, format, run_id: runId })}`
