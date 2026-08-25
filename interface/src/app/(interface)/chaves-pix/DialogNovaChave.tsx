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
import { SeletorDePapel, type OpcaoDeDono } from "./SeletorDePapel"
import { papelPedeDono, type ChavePix, type PapelDaChave, type SugestaoDeChave } from "./_tipos"

/**
 * Cadastrar uma chave. O papel **não tem default**, e isso é de propósito (ADR-0049 §2): um
 * default `casa` faria o próximo cadastro distraído chamar de casa a chave de um terceiro, que é
 * exatamente a confusão que este registro existe para acabar. O formulário abre em `casa` porque
 * alguma coisa tem que estar marcada, e a explicação abaixo do controle diz o que isso significa.
 *
 * A mesma modelo pode ter várias chaves — CPF, telefone, aleatória — e ela troca de banco. Não há
 * nada a desfazer aqui: cadastrar a segunda chave dela é o caminho normal.
 *
 * Pontuação não distingue chave: `+55 71 99984 0879` e `+5571999840879` são a mesma, e a segunda
 * volta 409. É a mesma normalização que o OCR aplica ao que leu no comprovante.
 *
 * `sugestao` é o mesmo diálogo aberto pela fila do ticket 05 — a chave e o titular já vêm
 * preenchidos porque **foram lidos do comprovante**, e a pergunta fica no topo para o gestor
 * responder olhando o que ela já mostrou. O papel continua sem palpite: é ele a pergunta.
 */
export function DialogNovaChave({
  open,
  onOpenChange,
  modelos,
  telefonistas,
  onCriada,
  sugestao,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  modelos: OpcaoDeDono[]
  telefonistas: OpcaoDeDono[]
  onCriada: (c: ChavePix) => void
  sugestao?: SugestaoDeChave | null
}) {
  const [chave, setChave] = useState("")
  const [papel, setPapel] = useState<PapelDaChave>("casa")
  const [donoId, setDonoId] = useState<string | null>(null)
  const [titular, setTitular] = useState("")
  const [descricao, setDescricao] = useState("")
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    if (!open) return
    // Reset ao abrir — mesmo padrão do DialogNovoTelefonista.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setChave(sugestao?.chave ?? "")
    setPapel("casa")
    setDonoId(null)
    setTitular(sugestao?.titulares[0] ?? "")
    setDescricao("")
  }, [open, sugestao])

  const pede = papelPedeDono(papel)
  const invalido = chave.trim() === "" || (pede !== null && donoId === null)

  async function criar() {
    if (invalido) return
    setSalvando(true)
    try {
      const criada = await api<ChavePix>("/v1/financeiro/chaves-pix", {
        method: "POST",
        body: JSON.stringify({
          chave: chave.trim(),
          papel,
          modelo_id: pede === "modelo" ? donoId : null,
          vendedor_id: pede === "vendedor" ? donoId : null,
          titular: titular.trim() || null,
          descricao: descricao.trim() || null,
        }),
      })
      onCriada(criada)
      toast.success("Chave cadastrada.")
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
          <DialogTitle>Cadastrar chave Pix</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {sugestao && (
            <div className="rounded-md bg-muted px-3 py-2 ring-1 ring-border-subtle">
              <p className="text-[12.5px] text-text-primary">{sugestao.pergunta}</p>
              <p className="mt-1 text-[11px] text-text-muted">
                Chave e titular vieram do comprovante. O papel não — é ele a pergunta.
              </p>
            </div>
          )}
          <div>
            <Label htmlFor="chave-pix-valor">Chave</Label>
            <Input
              id="chave-pix-valor"
              value={chave}
              onChange={(e) => setChave(e.target.value)}
              placeholder="CPF, telefone, e-mail ou aleatória"
              className="mt-1 font-mono text-[13px]"
            />
            <p className="mt-1 text-[11px] text-text-muted">
              Pode digitar do jeito que estiver no banco — espaço, ponto e sinal não distinguem
              chave. Se ela já estiver cadastrada com outra pontuação, o cadastro avisa.
            </p>
          </div>

          <div>
            <Label>De quem é</Label>
            <div className="mt-1">
              <SeletorDePapel
                papel={papel}
                onPapel={setPapel}
                donoId={donoId}
                onDono={setDonoId}
                modelos={modelos}
                telefonistas={telefonistas}
                idPrefixo="nova-chave"
                disabled={salvando}
                modeloSugerida={sugestao?.modelo_id_sugerido}
              />
            </div>
          </div>

          <div>
            <Label htmlFor="chave-pix-titular">Titular — opcional</Label>
            <Input
              id="chave-pix-titular"
              value={titular}
              onChange={(e) => setTitular(e.target.value)}
              placeholder="Nome que aparece no comprovante"
              className="mt-1"
            />
            <p className="mt-1 text-[11px] text-text-muted">
              Serve para conferir de olho: é o nome que o OCR lê no destino da transferência, e ele
              nem sempre é o nome de quem a gente chama de dono da chave.
            </p>
          </div>

          <div>
            <Label htmlFor="chave-pix-descricao">Descrição — opcional</Label>
            <Input
              id="chave-pix-descricao"
              value={descricao}
              onChange={(e) => setDescricao(e.target.value)}
              placeholder="Banco, para que serve…"
              className="mt-1"
            />
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
