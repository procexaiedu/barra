"use client"

import { useState } from "react"
import { AlertTriangle, Check, Undo2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api, ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  foraDaFaixaOperacional,
  formatPercentual,
  lerPercentual,
  type Telefonista,
} from "./_tipos"

/**
 * Uma linha do cadastro: nome, percentual, WhatsApp e o botão de ativar/desativar.
 *
 * O percentual só vai para o servidor quando o gestor confirma (Salvar / Enter), e nunca a cada
 * tecla: "7" a caminho de "7,5" é um número válido e diferente, e salvar no meio da digitação
 * reprojetaria a comissão de todo mundo por um instante — sem snapshot, projeção errada é número
 * errado na tela de quem estiver olhando.
 */
export function LinhaTelefonista({
  telefonista,
  onSalvo,
}: {
  telefonista: Telefonista
  onSalvo: (t: Telefonista) => void
}) {
  const [nome, setNome] = useState(telefonista.nome)
  const [percentual, setPercentual] = useState(String(telefonista.percentual_comissao))
  const [jid, setJid] = useState(telefonista.whatsapp_jid ?? "")
  const [salvando, setSalvando] = useState(false)

  const percentualNum = lerPercentual(percentual)
  const jidLimpo = jid.trim()
  const nomeLimpo = nome.trim()

  const mudouNome = nomeLimpo !== telefonista.nome
  const mudouPercentual =
    percentualNum !== null && percentualNum !== telefonista.percentual_comissao
  const mudouJid = jidLimpo !== (telefonista.whatsapp_jid ?? "")
  const sujo = mudouNome || mudouPercentual || mudouJid
  const invalido = nomeLimpo === "" || percentualNum === null || percentualNum < 0

  function desfazer() {
    setNome(telefonista.nome)
    setPercentual(String(telefonista.percentual_comissao))
    setJid(telefonista.whatsapp_jid ?? "")
  }

  async function patch(corpo: Record<string, unknown>, mensagem: string) {
    setSalvando(true)
    try {
      const atualizado = await api<Telefonista>(
        `/v1/financeiro/telefonistas/${telefonista.id}`,
        { method: "PATCH", body: JSON.stringify(corpo) },
      )
      onSalvo(atualizado)
      toast.success(mensagem)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao salvar")
    } finally {
      setSalvando(false)
    }
  }

  async function salvar() {
    if (invalido || !sujo || percentualNum === null) return
    // Só o que mudou: PATCH parcial de verdade, para dois gestores editando campos diferentes na
    // mesma linha não sobrescreverem um ao outro com valor velho.
    const corpo: Record<string, unknown> = {}
    if (mudouNome) corpo.nome = nomeLimpo
    if (mudouPercentual) corpo.percentual_comissao = percentualNum
    if (mudouJid) corpo.whatsapp_jid = jidLimpo || null
    await patch(
      corpo,
      mudouPercentual
        ? `Comissão de ${nomeLimpo} agora é ${formatPercentual(percentualNum)}.`
        : "Cadastro atualizado.",
    )
  }

  const alerta = percentualNum !== null && foraDaFaixaOperacional(percentualNum)

  return (
    <li
      className={cn(
        "border-b border-border px-4 py-3 last:border-b-0",
        !telefonista.ativo && "opacity-60",
      )}
    >
      <div className="grid grid-cols-1 items-end gap-3 md:grid-cols-[minmax(0,1.4fr)_120px_minmax(0,1fr)_auto]">
        <label className="min-w-0">
          <span className="text-[11px] font-medium text-text-muted">Nome</span>
          <Input
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && salvar()}
            aria-label={`Nome de ${telefonista.nome}`}
            className="mt-1"
          />
        </label>

        <label>
          <span className="text-[11px] font-medium text-text-muted">Comissão</span>
          <div className="relative mt-1">
            <Input
              inputMode="decimal"
              value={percentual}
              onChange={(e) => setPercentual(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && salvar()}
              aria-label={`Percentual de comissão de ${telefonista.nome}`}
              aria-invalid={percentualNum === null || percentualNum < 0}
              className="pr-7 font-mono tabular-nums"
            />
            <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-[12px] text-text-muted">
              %
            </span>
          </div>
        </label>

        <label className="min-w-0">
          <span className="text-[11px] font-medium text-text-muted">WhatsApp (JID)</span>
          <Input
            value={jid}
            onChange={(e) => setJid(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && salvar()}
            placeholder="5511999999999@s.whatsapp.net"
            aria-label={`WhatsApp de ${telefonista.nome}`}
            className="mt-1 font-mono text-[12px]"
          />
        </label>

        <div className="flex items-center gap-1.5">
          {sujo ? (
            <>
              <Button size="sm" onClick={salvar} disabled={salvando || invalido}>
                <Check /> {salvando ? "Salvando…" : "Salvar"}
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={desfazer}
                disabled={salvando}
                aria-label="Desfazer alterações"
              >
                <Undo2 />
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant={telefonista.ativo ? "ghost" : "outline"}
              disabled={salvando}
              onClick={() =>
                patch(
                  { ativo: !telefonista.ativo },
                  telefonista.ativo
                    ? `${telefonista.nome} foi desativado.`
                    : `${telefonista.nome} voltou para a ativa.`,
                )
              }
            >
              {telefonista.ativo ? "Desativar" : "Reativar"}
            </Button>
          )}
        </div>
      </div>

      {alerta && (
        <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-warn-500">
          <AlertTriangle size={13} className="mt-px shrink-0" />
          Fora da faixa usual de 1% a 10%. Dá para salvar assim mesmo — só confira se é isso mesmo.
        </p>
      )}

      {!telefonista.whatsapp_jid && (
        <p className="mt-2 text-[11.5px] text-text-muted">
          Sem WhatsApp vinculado: as vendas que ele anunciar no grupo ficam sem vendedor e não
          geram comissão. O vínculo é o autor da mensagem — nunca o nome que aparece no grupo.
        </p>
      )}
    </li>
  )
}
