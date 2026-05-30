"use client"

import { useMemo, useState } from "react"

import { Combobox } from "@/components/ui/combobox"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { ATOR_LABEL, atorKey, parseAtorKey } from "@/lib/tarefas"
import type { AtorTipo, ResponsavelOpcao } from "@/tipos/tarefas"

/** Ordem canônica das abas; só renderiza as que têm gente. */
const ORDEM_TIPO: AtorTipo[] = ["usuario", "modelo", "vendedor"]

interface Props {
  /** Chave do ator (`atorKey`) ou "" para sem responsável. */
  value: string
  onChange: (v: string) => void
  responsaveis: ResponsavelOpcao[]
  id?: string
}

/**
 * Seletor de responsável da tarefa: separa o universo por tipo de ator
 * (Operador / Modelo / Vendedor) antes da busca, mantendo a lista curta.
 * `vendedor` só aparece quando o backend passar a incluí-lo (tabela do ADR 0012).
 */
export function SeletorResponsavel({ value, onChange, responsaveis, id }: Props) {
  const tiposDisponiveis = useMemo(() => {
    const presentes = new Set(responsaveis.map((r) => r.tipo))
    return ORDEM_TIPO.filter((t) => presentes.has(t))
  }, [responsaveis])

  const tipoDoValor = value ? parseAtorKey(value).tipo : null
  // Aba inicial: tipo do valor já atribuído, senão a primeira disponível.
  const [tipo, setTipo] = useState<AtorTipo>(tipoDoValor ?? tiposDisponiveis[0] ?? "modelo")

  const opcoesKeys = useMemo(
    () => responsaveis.filter((r) => r.tipo === tipo).map((r) => atorKey(r.tipo, r.id)),
    [responsaveis, tipo],
  )
  // Mapa global (todos os tipos) para o trigger exibir o nome mesmo quando a
  // aba ativa difere do tipo do valor selecionado.
  const nomePorKey = useMemo(() => {
    const m = new Map<string, string>()
    for (const r of responsaveis) m.set(atorKey(r.tipo, r.id), r.nome)
    return m
  }, [responsaveis])

  return (
    <div className="space-y-2">
      {tiposDisponiveis.length > 1 && (
        <div className="flex gap-1">
          {tiposDisponiveis.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTipo(t)}
              className={cn(
                "flex-1 rounded-md border px-2 py-1.5 text-xs font-medium transition-all duration-150",
                tipo === t
                  ? "border-border-brand bg-accent text-text-primary"
                  : "border-border text-text-secondary hover:bg-surface-hover",
              )}
            >
              {ATOR_LABEL[t]}
            </button>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Combobox
          id={id}
          value={value}
          onChange={onChange}
          options={opcoesKeys}
          placeholder="Sem responsável"
          displayFormat={(v) => nomePorKey.get(v) ?? v}
          className="flex-1"
        />
        {value && (
          <Button variant="ghost" size="sm" onClick={() => onChange("")}>
            Limpar
          </Button>
        )}
      </div>
    </div>
  )
}
