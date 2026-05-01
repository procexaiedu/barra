import { type SupabaseClient } from '@supabase/supabase-js'
import { createBrowserClient } from '@supabase/ssr'

let _client: SupabaseClient | null = null

function getClient(): SupabaseClient {
  if (_client) return _client
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  if (!url || !key) {
    // Retorna um client stub que não conecta — permite build sem env vars.
    // Em runtime, as env vars devem estar presentes.
    _client = createBrowserClient('http://localhost:54321', 'stub-key', {
      realtime: { params: { eventsPerSecond: 10 } },
    })
    return _client
  }
  _client = createBrowserClient(url, key, {
    realtime: { params: { eventsPerSecond: 10 } },
  })
  return _client
}

export const supabase = getClient()
