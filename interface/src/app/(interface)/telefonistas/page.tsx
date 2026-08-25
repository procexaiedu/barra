"use client"

import { useCallback, useEffect, useState } from "react"
import { UserPlus } from "lucide-react"
import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api, ApiError } from "@/lib/api"
import { DialogNovoTelefonista } from "./DialogNovoTelefonista"
import { LinhaTelefonista } from "./LinhaTelefonista"
import type { Telefonista, TelefonistasListaResponse } from "./_tipos"

/**
 * A aba **Telefonistas**, ao lado de Modelos (ADR-0048): quem vende e quanto leva.
 *
 * Pedida com essas palavras — *"cadastrar o nome deles, pra vocês conseguirem alterar os valores
 * da comissão deles"*. É a única tela onde esse número é mexido.
 *
 * ⚠️ O percentual é **projeção, sem snapshot**: mudá-lo aqui recalcula a comissão de todas as
 * vendas, inclusive as antigas. É decisão do domínio (a comissão do telefonista é da casa sobre
 * desempenho), e o oposto da comissão da modelo, que é negociada com ela e congelada na venda.
 *
 * ⚠️ Nada desta tela aparece no extrato da modelo: são duas pessoas, duas contas, e ela lê o
 * extrato dela junto com o gestor.
 */
export default function TelefonistasPage() {
  const [lista, setLista] = useState<Telefonista[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [incluirInativos, setIncluirInativos] = useState(false)
  const [criarOpen, setCriarOpen] = useState(false)

  const carregar = useCallback(async () => {
    try {
      const r = await api<TelefonistasListaResponse>(
        `/v1/financeiro/telefonistas?incluir_inativos=${incluirInativos}`,
      )
      setLista(r.items)
      setErro(null)
    } catch (e) {
      setErro(e instanceof ApiError ? e.detail : "Erro ao carregar telefonistas")
    }
  }, [incluirInativos])

  useEffect(() => {
    // `carregar` é async: os setState só rodam depois do await. Mesmo padrão do useTemporadas.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar()
  }, [carregar])

  // Depois de salvar, a linha volta do servidor já normalizada (nome sem espaço, JID vazio como
  // null). Trocar o item em vez de recarregar a lista preserva o que o gestor está digitando nas
  // OUTRAS linhas — recarregar tudo apagaria edições abertas ao lado.
  const trocar = (atualizado: Telefonista) =>
    setLista((atual) =>
      (atual ?? []).map((t) => (t.id === atualizado.id ? atualizado : t)),
    )

  // Desativar com o filtro em "só ativos" tira a linha da lista; é o comportamento certo, e o
  // botão "Mostrar inativos" é como ela volta.
  const aposSalvar = (atualizado: Telefonista) => {
    if (!incluirInativos && !atualizado.ativo) {
      setLista((atual) => (atual ?? []).filter((t) => t.id !== atualizado.id))
      return
    }
    trocar(atualizado)
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Telefonistas"
        description="Quem vende e quanto leva de comissão sobre o bruto vendido."
        action={{
          label: "Cadastrar telefonista",
          onClick: () => setCriarOpen(true),
          icon: <UserPlus size={16} strokeWidth={1.5} />,
        }}
      >
        <Button
          variant={incluirInativos ? "secondary" : "outline"}
          size="sm"
          aria-pressed={incluirInativos}
          onClick={() => setIncluirInativos((v) => !v)}
        >
          {incluirInativos ? "Mostrando inativos" : "Mostrar inativos"}
        </Button>
      </PageHeader>

      <section className="flex flex-col gap-3">
        <p className="text-[12px] leading-relaxed text-text-muted">
          A comissão incide sobre o <strong>faturamento bruto</strong> vendido — taxa de cartão não
          é descontada e deslocamento não entra. O cálculo é por projeção: mudar o percentual aqui
          recalcula também a comissão de vendas já feitas.
        </p>

        {erro && lista === null && (
          <div className="rounded-lg border border-danger-500/40 bg-[color:var(--danger-500)]/8 px-4 py-3">
            <p className="text-[13px] text-text-primary">{erro}</p>
            <button
              type="button"
              onClick={carregar}
              className="mt-2 text-[12px] font-medium text-text-brand underline underline-offset-2"
            >
              Tentar de novo
            </button>
          </div>
        )}

        {lista === null && erro === null && <Skeleton className="h-[220px] w-full rounded-lg" />}

        {lista !== null &&
          (lista.length === 0 ? (
            <div className="rounded-lg bg-card px-4 py-10 text-center ring-1 ring-border-subtle">
              <p className="text-[13px] text-text-primary">Nenhum telefonista cadastrado.</p>
              <p className="mt-1 text-[12px] text-text-muted">
                Cadastre quem posta as fichas no grupo. Sem cadastro, a venda anunciada fica sem
                vendedor e ninguém recebe comissão por ela.
              </p>
            </div>
          ) : (
            <ul
              aria-label="Telefonistas"
              className="overflow-hidden rounded-lg bg-card ring-1 ring-border-subtle shadow-elev-1"
            >
              {lista.map((t) => (
                <LinhaTelefonista key={t.id} telefonista={t} onSalvo={aposSalvar} />
              ))}
            </ul>
          ))}
      </section>

      <DialogNovoTelefonista
        open={criarOpen}
        onOpenChange={setCriarOpen}
        onCriado={(criado) => setLista((atual) => [...(atual ?? []), criado])}
      />
    </div>
  )
}
