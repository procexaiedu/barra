import { supabase } from './supabase'

export type RealtimeTabela =
  | 'atendimentos'
  | 'comprovantes_pix'
  | 'bloqueios'
  | 'eventos'
  | 'mensagens'
  | 'conversas'
  | 'clientes'

export function subscribeTabelas(canalNome: string, tabelas: RealtimeTabela[], onEvent: () => void) {
  const channels = tabelas.map((t) =>
    supabase.channel(`${canalNome}:${t}`)
      .on('postgres_changes', { event: '*', schema: 'barravips', table: t }, onEvent)
      .subscribe()
  )
  return () => channels.forEach((c) => supabase.removeChannel(c))
}
