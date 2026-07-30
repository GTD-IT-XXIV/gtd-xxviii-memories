const API_BASE = '/api'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new ApiError(res.status, text)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
}

export function thumbnailUrl(kind: 'photo' | 'face', id: number): string {
  return `${API_BASE}/${kind === 'photo' ? 'photos' : 'faces'}/${id}/thumbnail`
}

/** Prefixes a relative URL returned by the backend (e.g. "/clusters/5/thumbnail")
 * with the /api proxy base so it resolves correctly from the browser. */
export function apiUrl(relativeUrl: string): string {
  return `${API_BASE}${relativeUrl}`
}
