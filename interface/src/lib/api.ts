import { supabase } from './supabase'

const baseURL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public code: string | null = null,
    public details: Record<string, unknown> | null = null,
  ) {
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
    // Escopo local: o 401 é deste dispositivo. `signOut()` sem escopo revoga a
    // sessão em TODOS os aparelhos — um token vencido no desktop derrubaria o
    // celular da operadora junto.
    await supabase.auth.signOut({ scope: 'local' })
    if (typeof window !== 'undefined') window.location.assign('/login')
    throw new ApiError(401, 'Sessão expirada')
  }

  if (!r.ok) {
    let detail = `Erro ${r.status}`
    let code: string | null = null
    let details: Record<string, unknown> | null = null
    try {
      const body = await r.json()
      detail = body.detail ?? body.error?.message ?? detail
      code = body.error?.code ?? null
      details = body.error?.details ?? null
    } catch {}
    throw new ApiError(r.status, detail, code, details)
  }

  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}

export async function apiFormData<T>(path: string, formData: FormData): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  const r = await fetch(`${baseURL}${path}`, {
    method: "POST",
    body: formData,
    headers: {
      ...(session ? { authorization: `Bearer ${session.access_token}` } : {}),
    },
  })

  if (r.status === 401) {
    // Mesmo motivo do `api()`: escopo local, o 401 é só deste dispositivo.
    await supabase.auth.signOut({ scope: 'local' })
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
