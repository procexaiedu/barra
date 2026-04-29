// Fetcher tipado para a API FastAPI.
// Tipos virão de src/tipos/, gerados a partir do OpenAPI via scripts/gera_tipos_openapi.sh.

const baseURL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${baseURL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) throw new Error(`API ${r.status} em ${path}`);
  return r.json() as Promise<T>;
}
