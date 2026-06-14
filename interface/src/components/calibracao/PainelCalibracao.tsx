"use client"

import { toast } from "sonner"

import { ListaFalas } from "@/components/calibracao/ListaFalas"
import { SeletorRodada } from "@/components/calibracao/SeletorRodada"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useCalibracao } from "@/hooks/useCalibracao"

/** Aba "Calibrar judge" da tela de Avaliação: rotulagem double-blind (Fernando
 *  e sócia, independentes) de rodadas .jsonl para montar o golden.jsonl que
 *  calibra o LLM-judge (ADR 0015). Batch + 2 raters — distinto da avaliação
 *  ao vivo. */
export function PainelCalibracao() {
  const cal = useCalibracao()

  async function criar(nome: string, arquivo: File) {
    try {
      const nova = await cal.criar(nome, arquivo)
      toast.success(`Rodada "${nova.nome}" criada (${nova.total_falas} falas).`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha ao subir o arquivo.")
    }
  }

  async function exportar() {
    try {
      const r = await cal.exportar()
      if (!r) return
      if (r.total === 0) toast.warning("Nenhuma fala rotulada pelos dois ainda — golden vazio.")
      else toast.success(`golden.jsonl baixado (${r.total} falas).`)
      r.avisos.forEach((a) => toast.warning(a))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha ao exportar.")
    }
  }

  async function marcar(falaPk: string, passou: boolean, obs: string) {
    try {
      await cal.marcar(falaPk, passou, obs)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha ao salvar o rótulo.")
    }
  }

  let conteudo
  if (!cal.rodadaId) {
    conteudo = (
      <Card className="p-8 text-center text-sm text-text-muted">
        Selecione uma rodada ou suba um .jsonl para começar.
      </Card>
    )
  } else if (cal.status === "loading") {
    conteudo = (
      <div className="flex flex-col gap-4">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-40 w-full" />
        ))}
      </div>
    )
  } else if (cal.status === "error") {
    conteudo = <Card className="p-6 text-sm text-destructive">{cal.error}</Card>
  } else if (cal.dados && cal.dados.falas.length === 0) {
    conteudo = (
      <Card className="p-8 text-center text-sm text-text-muted">Esta rodada não tem falas.</Card>
    )
  } else if (cal.dados) {
    conteudo = <ListaFalas falas={cal.dados.falas} onMarcar={marcar} />
  }

  return (
    <div className="flex flex-col gap-6">
      <SeletorRodada
        rodadas={cal.rodadas}
        rodadaId={cal.rodadaId}
        onSelecionar={cal.selecionar}
        onCriar={criar}
        onExportar={exportar}
      />
      {conteudo}
    </div>
  )
}
