"use client"

import { useState } from "react"
import { Check, Star, Undo2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api, ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"
import { SeletorDePapel, type OpcaoDeDono } from "./SeletorDePapel"
import { ROTULO_DO_PAPEL, donoDaChave, papelPedeDono, type ChavePix, type PapelDaChave } from "./_tipos"

/**
 * Uma linha do registro: a chave, de quem ela é, a marca de padrão e o inativar.
 *
 * ⚠️ **Não existe excluir.** Chave que saiu de uso continua explicando os comprovantes antigos que
 * apontam para ela — apagá-la transformaria um Pix já conciliado em "destino desconhecido" meses
 * depois. O botão é *Inativar*, e a chave volta com "Mostrar inativas".
 *
 * ⚠️ Marcar esta como padrão **desmarca a anterior** — o servidor faz as duas escritas na mesma
 * transação, porque só pode existir uma. A tela recarrega a lista depois disso: a linha que perdeu
 * a marca é outra, e mostrar duas estrelas por um instante seria mentira.
 */
export function LinhaChavePix({
  chave,
  modelos,
  telefonistas,
  onSalvo,
  onPadraoTrocada,
}: {
  chave: ChavePix
  modelos: OpcaoDeDono[]
  telefonistas: OpcaoDeDono[]
  onSalvo: (c: ChavePix) => void
  onPadraoTrocada: () => void
}) {
  const [papel, setPapel] = useState<PapelDaChave>(chave.papel)
  const [donoId, setDonoId] = useState<string | null>(chave.modelo_id ?? chave.vendedor_id)
  const [titular, setTitular] = useState(chave.titular ?? "")
  const [descricao, setDescricao] = useState(chave.descricao ?? "")
  const [salvando, setSalvando] = useState(false)

  const donoOriginal = chave.modelo_id ?? chave.vendedor_id
  const mudouPapel = papel !== chave.papel
  const mudouDono = donoId !== donoOriginal
  const mudouTitular = titular.trim() !== (chave.titular ?? "")
  const mudouDescricao = descricao.trim() !== (chave.descricao ?? "")
  const sujo = mudouPapel || mudouDono || mudouTitular || mudouDescricao
  const pede = papelPedeDono(papel)
  const invalido = pede !== null && donoId === null

  function desfazer() {
    setPapel(chave.papel)
    setDonoId(donoOriginal)
    setTitular(chave.titular ?? "")
    setDescricao(chave.descricao ?? "")
  }

  async function patch(corpo: Record<string, unknown>, mensagem: string) {
    setSalvando(true)
    try {
      const atualizada = await api<ChavePix>(`/v1/financeiro/chaves-pix/${chave.id}`, {
        method: "PATCH",
        body: JSON.stringify(corpo),
      })
      onSalvo(atualizada)
      toast.success(mensagem)
      return atualizada
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao salvar")
      return null
    } finally {
      setSalvando(false)
    }
  }

  async function salvar() {
    if (invalido || !sujo) return
    const corpo: Record<string, unknown> = {}
    if (mudouPapel || mudouDono) {
      // Papel e dono viajam juntos: o PATCH reescreve os dois, e mandar só um deixaria a linha com
      // dois donos discordando.
      corpo.papel = papel
      corpo.modelo_id = pede === "modelo" ? donoId : null
      corpo.vendedor_id = pede === "vendedor" ? donoId : null
    }
    if (mudouTitular) corpo.titular = titular.trim() || null
    if (mudouDescricao) corpo.descricao = descricao.trim() || null
    await patch(corpo, "Chave atualizada.")
  }

  async function marcarPadrao() {
    const nova = await patch({ padrao: true }, "Esta agora é a chave padrão da casa.")
    if (nova) onPadraoTrocada()
  }

  return (
    <li className={cn("border-b border-border px-4 py-4 last:border-b-0", !chave.ativo && "opacity-60")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-[13px] text-text-primary">{chave.chave}</p>
          <p className="mt-0.5 text-[11px] text-text-muted">
            {ROTULO_DO_PAPEL[chave.papel]}
            {donoDaChave(chave) ? ` · ${donoDaChave(chave)}` : ""}
            {chave.ativo ? "" : " · inativa"}
          </p>
        </div>

        <div className="flex items-center gap-1.5">
          {chave.padrao ? (
            <span className="flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-[11px] font-medium text-text-primary">
              <Star size={12} className="fill-current" /> Padrão da casa
            </span>
          ) : (
            chave.papel === "casa" &&
            chave.ativo && (
              <Button size="sm" variant="ghost" onClick={marcarPadrao} disabled={salvando}>
                <Star /> Tornar padrão
              </Button>
            )
          )}
          <Button
            size="sm"
            variant={chave.ativo ? "ghost" : "outline"}
            disabled={salvando}
            onClick={() =>
              patch(
                { ativo: !chave.ativo },
                chave.ativo
                  ? chave.padrao
                    ? "Chave inativada — a casa ficou sem chave padrão. Escolha outra."
                    : "Chave inativada. Ela continua explicando comprovantes antigos."
                  : "Chave reativada.",
              )
            }
          >
            {chave.ativo ? "Inativar" : "Reativar"}
          </Button>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <SeletorDePapel
          papel={papel}
          onPapel={setPapel}
          donoId={donoId}
          onDono={setDonoId}
          modelos={modelos}
          telefonistas={telefonistas}
          idPrefixo={`chave-${chave.id}`}
          disabled={salvando}
        />

        <div className="flex flex-col gap-2">
          <label className="min-w-0">
            <span className="text-[11px] font-medium text-text-muted">Titular</span>
            <Input
              value={titular}
              onChange={(e) => setTitular(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && salvar()}
              placeholder="Nome que aparece no comprovante"
              aria-label={`Titular da chave ${chave.chave}`}
              className="mt-1"
            />
          </label>
          <label className="min-w-0">
            <span className="text-[11px] font-medium text-text-muted">Descrição</span>
            <Input
              value={descricao}
              onChange={(e) => setDescricao(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && salvar()}
              placeholder="Banco, para que serve…"
              aria-label={`Descrição da chave ${chave.chave}`}
              className="mt-1"
            />
          </label>
        </div>
      </div>

      {sujo && (
        <div className="mt-3 flex items-center gap-1.5">
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
        </div>
      )}
    </li>
  )
}
