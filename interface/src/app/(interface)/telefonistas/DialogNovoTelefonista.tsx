"use client"

import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, ApiError } from "@/lib/api"
import {
  foraDaFaixaOperacional,
  lerPercentual,
  PERCENTUAL_PADRAO,
  type Telefonista,
} from "./_tipos"

/**
 * Cadastrar um telefonista. O percentual já nasce em 7% — a referência que o dono deu — e é para
 * ser mudado por pessoa, "dependendo da experiência do vendedor".
 *
 * O WhatsApp é opcional aqui e obrigatório na prática: sem ele, o autor da ficha no grupo não
 * resolve para ninguém e a venda fica sem vendedor. Fica opcional porque o gestor nem sempre tem
 * o JID à mão na hora de cadastrar, e travar o cadastro por isso empurraria o problema para fora
 * do sistema.
 */
export function DialogNovoTelefonista({
  open,
  onOpenChange,
  onCriado,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCriado: (t: Telefonista) => void
}) {
  const [nome, setNome] = useState("")
  const [percentual, setPercentual] = useState(String(PERCENTUAL_PADRAO))
  const [jid, setJid] = useState("")
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    if (!open) return
    // Reset ao abrir — mesmo padrão do DialogVale; o lint lê como setState síncrono.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNome("")
    setPercentual(String(PERCENTUAL_PADRAO))
    setJid("")
  }, [open])

  const percentualNum = lerPercentual(percentual)
  const invalido = nome.trim() === "" || percentualNum === null || percentualNum < 0

  async function criar() {
    if (invalido || percentualNum === null) return
    setSalvando(true)
    try {
      const criado = await api<Telefonista>("/v1/financeiro/telefonistas", {
        method: "POST",
        body: JSON.stringify({
          nome: nome.trim(),
          percentual_comissao: percentualNum,
          whatsapp_jid: jid.trim() || null,
        }),
      })
      onCriado(criado)
      toast.success(`${criado.nome} cadastrado.`)
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao cadastrar")
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>Cadastrar telefonista</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div>
            <Label htmlFor="telefonista-nome">Nome</Label>
            <Input
              id="telefonista-nome"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              placeholder="Nome do telefonista"
              className="mt-1"
            />
          </div>

          <div>
            <Label htmlFor="telefonista-percentual">Comissão (%)</Label>
            <Input
              id="telefonista-percentual"
              inputMode="decimal"
              value={percentual}
              onChange={(e) => setPercentual(e.target.value)}
              aria-invalid={percentualNum === null || percentualNum < 0}
              className="mt-1 font-mono tabular-nums"
            />
            <p className="mt-1 text-[11px] text-text-muted">
              Sobre o faturamento bruto que ele vendeu. Deslocamento não entra na base — é
              reembolso de custo, não venda.
            </p>
            {percentualNum !== null && foraDaFaixaOperacional(percentualNum) && (
              <p className="mt-1 text-[11px] text-warn-500">
                Fora da faixa usual de 1% a 10%.
              </p>
            )}
          </div>

          <div>
            <Label htmlFor="telefonista-jid">WhatsApp (JID) — opcional</Label>
            <Input
              id="telefonista-jid"
              value={jid}
              onChange={(e) => setJid(e.target.value)}
              placeholder="5511999999999@s.whatsapp.net"
              className="mt-1 font-mono text-[12px]"
            />
            <p className="mt-1 text-[11px] text-text-muted">
              É por aqui que a venda anunciada no grupo vira comissão dele: vale o autor da
              mensagem, nunca o nome exibido. Sem JID, a venda fica sem vendedor.
            </p>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={salvando}>
            Cancelar
          </Button>
          <Button onClick={criar} disabled={salvando || invalido}>
            {salvando ? "Cadastrando…" : "Cadastrar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
