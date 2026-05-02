import { supabase } from './supabase'

const baseURL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail)
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  const r = await fetch(`${baseURL}${path}`, {
    ...init,
    headers: {
      'content-type': 'application/json',
      ...(session ? { authorization: `Bearer ${session.access_token}` } : {}),
      ...(init?.headers ?? {}),
    },
  })

  if (r.status === 401) {
    await supabase.auth.signOut()
    if (typeof window !== 'undefined') window.location.assign('/login')
    throw new ApiError(401, 'Sessão expirada')
  }

  if (!r.ok) {
    let detail = `Erro ${r.status}`
    try {
      const body = await r.json()
      detail = body.detail ?? body.error?.message ?? detail
    } catch {}
    throw new ApiError(r.status, detail)
  }

  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}
