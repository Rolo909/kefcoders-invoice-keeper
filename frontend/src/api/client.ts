export const API_PREFIX = '/api/v1';

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public code: string | null,
  ) {
    super(detail);
  }
}

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: (() => void) | null) => {
  onUnauthorized = fn;
};

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

export function buildQuery(query?: Query) {
  if (!query) return '';
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) value.forEach((v) => qs.append(key, v));
    else qs.append(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
}

function readDetail(body: unknown, fallback: string) {
  if (!body || typeof body !== 'object') return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d))).join('; ');
  }
  return fallback;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown; query?: Query } = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const res = await fetch(`${API_PREFIX}${path}${buildQuery(init.query)}`, {
    method: init.method ?? 'GET',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(init.body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : {}),
    },
    body: init.body === undefined ? undefined : isForm ? (init.body as FormData) : JSON.stringify(init.body),
  });

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }

  if (!res.ok) {
    if (res.status === 401 && path !== '/auth/login' && path !== '/auth/me') onUnauthorized?.();
    const fallback = res.status >= 500 ? 'Сервер не отвечает. Попробуйте ещё раз через минуту.' : `Ошибка ${res.status}`;
    const code = body && typeof body === 'object' && 'code' in body ? String((body as { code: unknown }).code) : null;
    throw new ApiError(res.status, readDetail(body, fallback), code);
  }
  return body as T;
}

export const downloadUrl = (attachmentId: string) => `${API_PREFIX}/attachments/${attachmentId}/download`;
