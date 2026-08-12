"use client"

import { useMemo, useState } from "react"
import { Check, Loader2, Pencil, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { DialogAdicionarServicoModelo } from "@/components/modelos/DialogAdicionarServicoModelo"
import { FeticheValor } from "@/components/comum/FeticheValor"
import { PisoValor } from "@/components/comum/PisoValor"
import { ApiError } from "@/lib/api"
import { formatBRL } from "@/lib/formatters"
import {
  corpoAtualizarPreco,
  lerPrecoMinimo,
  mensagemPrecoAbaixoDoPiso,
  pisoDoErro422,
  precoViolaPiso,
} from "@/lib/precoMinimo"
import type {
  Duracao,
  DuracaoInput,
  Fetiche,
  FeticheInput,
  FeticheModeloVinculo,
  Programa,
  ProgramaInput,
  ProgramaModeloVinculo,
  SalvarPrecoProgramaFn,
} from "@/tipos/modelos"

export function ProgramasModelo({
  catalogo,
  duracoes,
  vinculados,
  onVincular,
  onAtualizarPreco,
  onDesvincular,
  onCriarPrograma,
  onCriarDuracao,
  catalogoFetiches,
  fetichesVinculados,
  onVincularFetiche,
  onAtualizarFetiche,
  onDesvincularFetiche,
  onCriarFetiche,
}: {
  catalogo: Programa[]
  duracoes: Duracao[]
  vinculados: ProgramaModeloVinculo[]
  onVincular: SalvarPrecoProgramaFn
  onAtualizarPreco: SalvarPrecoProgramaFn
  onDesvincular: (programaId: string, duracaoId: string) => Promise<void>
  onCriarPrograma: (input: ProgramaInput) => Promise<Programa>
  onCriarDuracao: (input: DuracaoInput) => Promise<Duracao>
  catalogoFetiches: Fetiche[]
  fetichesVinculados: FeticheModeloVinculo[]
  onVincularFetiche: (feticheId: string, preco: number | null) => Promise<void>
  onAtualizarFetiche: (feticheId: string, preco: number | null) => Promise<void>
  onDesvincularFetiche: (feticheId: string) => Promise<void>
  onCriarFetiche: (input: FeticheInput) => Promise<Fetiche>
}) {
  const [dialogOpen, setDialogOpen] = useState(false)

  const grupos = useMemo(() => agruparPorPrograma(vinculados), [vinculados])

  return (
    <section className="rounded-lg bg-card p-6 shadow-elev-1 ring-1 ring-border-subtle">
      <header className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Serviços e preços
          </h2>
          <p className="mt-1 pl-[14px] text-sm text-text-muted">
            Cadastre apenas o que esta modelo realmente oferece.
          </p>
          {/* ADR-0037: o piso é por LINHA e vence o percentual global da casa. Quem lê a tela
              precisa entender isso sem abrir documentação. */}
          <p className="mt-1 pl-[14px] text-xs text-text-muted">
            <span className="text-text-secondary">Mínimo</span> = o menor valor que a IA pode
            ofertar naquela linha. Sem mínimo, vale só o desconto padrão da casa; mínimo igual ao
            preço trava a linha (não desconta).
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setDialogOpen(true)}>
          <Plus size={13} strokeWidth={1.5} />
          Adicionar serviço
        </Button>
      </header>

      {vinculados.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-muted px-4 py-10 text-center">
          <p className="text-sm text-text-secondary">Nenhum serviço cadastrado ainda.</p>
          <p className="mt-1 text-xs text-text-muted">
            Use{" "}
            <button
              type="button"
              onClick={() => setDialogOpen(true)}
              className="text-text-primary underline-offset-2 hover:underline cursor-pointer"
            >
              Adicionar serviço
            </button>{" "}
            para definir o que ela faz e os preços de cada duração.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {grupos.map((grupo) => (
            <GrupoPrograma
              key={grupo.programaId}
              grupo={grupo}
              onAtualizarPreco={onAtualizarPreco}
              onDesvincular={onDesvincular}
            />
          ))}
        </div>
      )}

      <DialogAdicionarServicoModelo
        open={dialogOpen}
        catalogo={catalogo}
        duracoes={duracoes}
        vinculados={vinculados}
        onOpenChange={setDialogOpen}
        onCriarPrograma={onCriarPrograma}
        onCriarDuracao={onCriarDuracao}
        onVincular={onVincular}
      />

      <FetichesSubBloco
        catalogo={catalogoFetiches}
        vinculados={fetichesVinculados}
        onVincular={onVincularFetiche}
        onAtualizarFetiche={onAtualizarFetiche}
        onDesvincular={onDesvincularFetiche}
        onCriar={onCriarFetiche}
      />
    </section>
  )
}

interface GrupoProgramaItem {
  programaId: string
  nome: string
  categoria: string | null
  linhas: ProgramaModeloVinculo[]
}

function agruparPorPrograma(vinculados: ProgramaModeloVinculo[]): GrupoProgramaItem[] {
  const map = new Map<string, GrupoProgramaItem>()
  for (const v of vinculados) {
    const existente = map.get(v.programa_id)
    if (existente) {
      existente.linhas.push(v)
    } else {
      map.set(v.programa_id, {
        programaId: v.programa_id,
        nome: v.nome,
        categoria: v.categoria,
        linhas: [v],
      })
    }
  }
  return Array.from(map.values())
}

function GrupoPrograma({
  grupo,
  onAtualizarPreco,
  onDesvincular,
}: {
  grupo: GrupoProgramaItem
  onAtualizarPreco: SalvarPrecoProgramaFn
  onDesvincular: (programaId: string, duracaoId: string) => Promise<void>
}) {
  return (
    <div className="overflow-hidden rounded-md border border-border shadow-elev-1">
      <div className="border-b border-border bg-muted px-4 py-2.5">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
          <span className="h-3 w-0.5 rounded-full bg-gold-500/70" aria-hidden />
          {grupo.nome}
        </h3>
      </div>
      <ul className="divide-y divide-border">
        {grupo.linhas.map((linha) => (
          <LinhaServico
            key={`${linha.programa_id}:${linha.duracao_id}`}
            linha={linha}
            onAtualizarPreco={onAtualizarPreco}
            onDesvincular={onDesvincular}
          />
        ))}
      </ul>
    </div>
  )
}

function LinhaServico({
  linha,
  onAtualizarPreco,
  onDesvincular,
}: {
  linha: ProgramaModeloVinculo
  onAtualizarPreco: SalvarPrecoProgramaFn
  onDesvincular: (programaId: string, duracaoId: string) => Promise<void>
}) {
  const [editando, setEditando] = useState(false)
  const [precoInput, setPrecoInput] = useState("")
  const [minimoInput, setMinimoInput] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const abrirEdicao = () => {
    setPrecoInput(String(linha.preco))
    // Piso desconhecido (backend não devolve na listagem) abre vazio e, intocado, não vai no
    // PATCH — o `corpoAtualizarPreco` cuida disso. Vazio aqui nunca significa "apague o piso"
    // sozinho; só depois de o operador mexer.
    setMinimoInput(linha.preco_minimo == null ? "" : String(linha.preco_minimo))
    setEditando(true)
  }

  const cancelar = () => {
    setEditando(false)
    setPrecoInput("")
    setMinimoInput("")
  }

  const confirmar = async () => {
    const preco = Number(precoInput.replace(",", "."))
    if (!precoInput.trim() || isNaN(preco) || preco < 0) {
      toast.error("Informe um preço válido")
      return
    }
    const lido = lerPrecoMinimo(minimoInput, preco)
    if ("erro" in lido) {
      toast.error(lido.erro)
      return
    }
    const corpo = corpoAtualizarPreco({
      preco,
      minimo: lido.minimo,
      minimoOriginal: linha.preco_minimo,
    })
    // Preço novo furando um piso que o painel já conhece e que o operador não mexeu: o backend
    // devolveria 422. Dizer aqui poupa a ida ao servidor.
    if (!("preco_minimo" in corpo) && precoViolaPiso(preco, linha.preco_minimo)) {
      toast.error(mensagemPrecoAbaixoDoPiso(preco, linha.preco_minimo))
      return
    }
    setSubmitting(true)
    try {
      await onAtualizarPreco(linha.programa_id, linha.duracao_id, preco, corpo.preco_minimo)
      toast.success(
        !("preco_minimo" in corpo)
          ? "Preço atualizado"
          : corpo.preco_minimo === null
            ? "Preço atualizado e mínimo removido"
            : "Preço e mínimo atualizados",
      )
      setEditando(false)
    } catch (e) {
      // 422 do PATCH sem `preco_minimo`: o servidor conhece um piso que a tela não conhecia.
      // Preenche o campo com ele para o operador ajustar os dois de uma vez.
      if (e instanceof ApiError && e.status === 422) {
        const piso = pisoDoErro422(e.detail)
        if (piso !== null) {
          setMinimoInput(String(piso))
          toast.error(mensagemPrecoAbaixoDoPiso(preco, piso))
          return
        }
      }
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSubmitting(false)
    }
  }

  const remover = async () => {
    setSubmitting(true)
    try {
      await onDesvincular(linha.programa_id, linha.duracao_id)
      toast.success("Serviço removido")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao remover")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-surface-hover">
      <span className="w-28 shrink-0 text-sm text-text-secondary">{linha.duracao_nome}</span>

      <div className="ml-auto flex items-center gap-2">
        {editando ? (
          <>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-muted">
                Preço
              </span>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-text-muted">R$</span>
                <Input
                  type="number"
                  min={0}
                  step={50}
                  value={precoInput}
                  onChange={(e) => setPrecoInput(e.target.value)}
                  placeholder="Ex.: 800"
                  aria-label="Preço de tabela"
                  className="h-8 w-28 bg-input font-mono text-sm tabular-nums"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter") confirmar()
                    if (e.key === "Escape") cancelar()
                  }}
                />
              </div>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-muted">
                Mínimo
              </span>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-text-muted">R$</span>
                <Input
                  type="number"
                  min={0}
                  step={50}
                  value={minimoInput}
                  onChange={(e) => setMinimoInput(e.target.value)}
                  placeholder="sem mínimo"
                  aria-label="Preço mínimo (vazio = sem mínimo)"
                  className="h-8 w-28 bg-input font-mono text-sm tabular-nums"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") confirmar()
                    if (e.key === "Escape") cancelar()
                  }}
                />
              </div>
            </label>
            <Button variant="primary" size="icon-sm" onClick={confirmar} disabled={submitting} aria-label="Salvar preço" className="self-end">
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} strokeWidth={2} />}
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={cancelar} disabled={submitting} aria-label="Cancelar" className="self-end">
              <X size={14} strokeWidth={1.5} />
            </Button>
          </>
        ) : (
          <>
            <div className="flex flex-col items-end gap-0.5">
              <span className="font-mono text-sm font-medium tabular-nums text-text-primary">
                {formatBRL(linha.preco)}
              </span>
              <PisoValor preco={linha.preco} precoMinimo={linha.preco_minimo} />
            </div>
            <Button variant="ghost" size="icon-sm" onClick={abrirEdicao} disabled={submitting} aria-label="Editar preço">
              <Pencil size={14} strokeWidth={1.5} />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={remover}
              disabled={submitting}
              aria-label="Remover serviço"
              className="hover:text-state-lost"
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <X size={14} strokeWidth={1.5} />}
            </Button>
          </>
        )}
      </div>

      {editando && (
        <p className="w-full text-right text-[11px] leading-relaxed text-text-muted">
          Mínimo vazio = sem piso (vale só o desconto padrão da casa). Mínimo igual ao preço = esta
          linha não desconta.
        </p>
      )}
    </li>
  )
}

// ── Sub-bloco Fetiches ─────────────────────────────────────────────────────────
// Fetiche é um extra sem duração (ADR-0030, revisão de 11/08/2026): o valor cadastrado AQUI é o
// extra cobrado, fixo, independente da duração do pacote. Campo vazio = incluso. Vive dentro da
// seção "Serviços e preços", separado das linhas de programa×duração.

// Piso do extra cadastrado. Abaixo dele o backend lê a coluna como o sentinel legado de "pago sem
// valor" (PRECO_FETICHE_CADASTRADO_MINIMO, api/dominio/atendimentos/service.py) e o extra vira um
// valor DERIVADO do pacote — R$5 digitado aqui sairia do tamanho do programa. A API devolve 422;
// o campo avisa antes. Vazio (e 0) continuam significando incluso.
const PRECO_FETICHE_MINIMO = 10

/**
 * Lê o campo de preço do fetiche: vazio = incluso (`preco: null`); número = o extra. Entrada que
 * não serve volta como `erro` — o chamador mostra o toast e não envia.
 */
function lerPrecoFetiche(texto: string): { preco: number | null } | { erro: string } {
  if (!texto.trim()) return { preco: null }
  const preco = Number(texto.replace(",", "."))
  if (isNaN(preco) || preco < 0) {
    return { erro: "Informe um preço válido (ou deixe vazio para incluso)" }
  }
  if (preco > 0 && preco < PRECO_FETICHE_MINIMO) {
    return {
      erro: `Preço abaixo de R$${PRECO_FETICHE_MINIMO} é lido como "pago sem valor" e viraria um extra do tamanho do programa. Deixe vazio para incluso, ou cobre a partir de R$${PRECO_FETICHE_MINIMO}.`,
    }
  }
  return { preco }
}

/**
 * ADR-0039: composição (casal/ménage) deixou de ter conta própria — a IA soma esse valor UMA vez
 * por cima do pacote, igual a qualquer outro extra. O `× 2` morreu: o número cadastrado é o total.
 */
function AvisoPorPessoa() {
  return (
    <p className="mt-1.5 text-xs leading-relaxed text-text-muted">
      <span className="text-text-primary">Segunda pessoa:</span> digite o valor TOTAL do extra
      pelas duas — a IA soma esse valor uma vez por cima do pacote, sem dobrar nada.
    </p>
  )
}

function FetichesSubBloco({
  catalogo,
  vinculados,
  onVincular,
  onAtualizarFetiche,
  onDesvincular,
  onCriar,
}: {
  catalogo: Fetiche[]
  vinculados: FeticheModeloVinculo[]
  onVincular: (feticheId: string, preco: number | null) => Promise<void>
  onAtualizarFetiche: (feticheId: string, preco: number | null) => Promise<void>
  onDesvincular: (feticheId: string) => Promise<void>
  onCriar: (input: FeticheInput) => Promise<Fetiche>
}) {
  const [selecionado, setSelecionado] = useState("")
  const [precoNovo, setPrecoNovo] = useState("")
  const [novoNome, setNovoNome] = useState("")
  const [criandoNovo, setCriandoNovo] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const vinculadosIds = useMemo(() => new Set(vinculados.map((f) => f.fetiche_id)), [vinculados])
  const disponiveis = useMemo(
    () => catalogo.filter((f) => !vinculadosIds.has(f.id)),
    [catalogo, vinculadosIds],
  )

  const adicionar = async () => {
    if (!selecionado) return
    const lido = lerPrecoFetiche(precoNovo)
    if ("erro" in lido) {
      toast.error(lido.erro)
      return
    }
    setSubmitting(true)
    try {
      await onVincular(selecionado, lido.preco)
      toast.success("Fetiche adicionado")
      setSelecionado("")
      setPrecoNovo("")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao adicionar fetiche")
    } finally {
      setSubmitting(false)
    }
  }

  const criarEAdicionar = async () => {
    if (!novoNome.trim()) return
    setSubmitting(true)
    try {
      const novo = await onCriar({ nome: novoNome.trim() })
      await onVincular(novo.id, null)
      toast.success("Fetiche criado e adicionado")
      setNovoNome("")
      setCriandoNovo(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao criar fetiche")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mt-6 border-t border-border pt-5">
      <div className="mb-3">
        <h3 className="flex items-center gap-2.5 text-sm font-semibold text-text-primary">
          <span className="h-3.5 w-1 rounded-full bg-gold-500" aria-hidden />
          Fetiches
        </h3>
        <p className="mt-1 pl-[14px] text-xs text-text-muted">
          O que ela faz. Preço vazio = incluso no programa; com valor, a IA cota esse extra por cima.
        </p>
      </div>

      {vinculados.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-muted px-4 py-6 text-center text-sm text-text-secondary">
          Nenhum fetiche marcado ainda.
        </p>
      ) : (
        <ul className="divide-y divide-border overflow-hidden rounded-md border border-border">
          {vinculados.map((f) => (
            <LinhaFetiche
              key={f.fetiche_id}
              linha={f}
              onAtualizarFetiche={onAtualizarFetiche}
              onDesvincular={onDesvincular}
            />
          ))}
        </ul>
      )}

      {disponiveis.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select
            value={selecionado}
            onChange={(e) => setSelecionado(e.target.value)}
            className="h-9 flex-1 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <option value="">Escolher fetiche…</option>
            {disponiveis.map((f) => (
              <option key={f.id} value={f.id}>{f.nome}</option>
            ))}
          </select>
          <span className="text-xs text-text-muted">R$</span>
          <Input
            type="number"
            min={PRECO_FETICHE_MINIMO}
            step={50}
            value={precoNovo}
            onChange={(e) => setPrecoNovo(e.target.value)}
            placeholder="incluso"
            aria-label="Preço do extra (vazio = incluso)"
            className="h-9 w-28 bg-input font-mono text-sm tabular-nums"
            onKeyDown={(e) => { if (e.key === "Enter") adicionar() }}
          />
          <Button variant="secondary" size="sm" onClick={adicionar} disabled={!selecionado || submitting}>
            {submitting ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} strokeWidth={1.5} />}
            Marcar
          </Button>
          {catalogo.find((f) => f.id === selecionado)?.cobra_por_pessoa && (
            <div className="w-full"><AvisoPorPessoa /></div>
          )}
        </div>
      )}

      {criandoNovo ? (
        <div className="mt-2 flex items-center gap-2 rounded-lg border border-dashed border-border bg-muted p-2">
          <Input
            value={novoNome}
            onChange={(e) => setNovoNome(e.target.value)}
            placeholder="Nome do novo fetiche"
            className="h-8 flex-1 bg-input text-sm"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter") criarEAdicionar()
              if (e.key === "Escape") { setNovoNome(""); setCriandoNovo(false) }
            }}
          />
          <Button variant="primary" size="icon-sm" onClick={criarEAdicionar} disabled={!novoNome.trim() || submitting} aria-label="Criar e marcar">
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} strokeWidth={2} />}
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => { setNovoNome(""); setCriandoNovo(false) }} disabled={submitting} aria-label="Cancelar">
            <X size={14} strokeWidth={1.5} />
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setCriandoNovo(true)}
          className="mt-2 inline-flex items-center gap-1 text-xs text-text-muted transition-colors hover:text-text-brand"
        >
          <Plus size={12} strokeWidth={1.5} />
          Criar novo fetiche no catálogo
        </button>
      )}
    </div>
  )
}

// Edição do extra espelha LinhaServico (lápis → input → confirmar/cancelar), com uma diferença:
// aqui o campo pode ficar vazio, e vazio significa incluso.
function LinhaFetiche({
  linha,
  onAtualizarFetiche,
  onDesvincular,
}: {
  linha: FeticheModeloVinculo
  onAtualizarFetiche: (feticheId: string, preco: number | null) => Promise<void>
  onDesvincular: (feticheId: string) => Promise<void>
}) {
  const [editando, setEditando] = useState(false)
  const [precoInput, setPrecoInput] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const abrirEdicao = () => {
    setPrecoInput(linha.preco === null ? "" : String(linha.preco))
    setEditando(true)
  }

  const cancelar = () => {
    setEditando(false)
    setPrecoInput("")
  }

  const confirmar = async () => {
    const lido = lerPrecoFetiche(precoInput)
    if ("erro" in lido) {
      toast.error(lido.erro)
      return
    }
    setSubmitting(true)
    try {
      await onAtualizarFetiche(linha.fetiche_id, lido.preco)
      toast.success(lido.preco === null ? "Fetiche marcado como incluso" : "Preço atualizado")
      setEditando(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSubmitting(false)
    }
  }

  const remover = async () => {
    setSubmitting(true)
    try {
      await onDesvincular(linha.fetiche_id)
      toast.success("Fetiche removido")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao remover")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-surface-hover">
      <span className="text-sm text-text-secondary">{linha.nome}</span>

      <div className="ml-auto flex items-center gap-2">
        {editando ? (
          <>
            <span className="text-xs text-text-muted">R$</span>
            <Input
              type="number"
              min={PRECO_FETICHE_MINIMO}
              step={50}
              value={precoInput}
              onChange={(e) => setPrecoInput(e.target.value)}
              placeholder="incluso"
              aria-label="Preço do extra (vazio = incluso)"
              className="h-8 w-28 bg-input font-mono text-sm tabular-nums"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") confirmar()
                if (e.key === "Escape") cancelar()
              }}
            />
            <Button variant="primary" size="icon-sm" onClick={confirmar} disabled={submitting} aria-label="Salvar preço">
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} strokeWidth={2} />}
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={cancelar} disabled={submitting} aria-label="Cancelar">
              <X size={14} strokeWidth={1.5} />
            </Button>
          </>
        ) : (
          <>
            <FeticheValor preco={linha.preco} />
            <Button variant="ghost" size="icon-sm" onClick={abrirEdicao} disabled={submitting} aria-label="Editar preço do fetiche">
              <Pencil size={14} strokeWidth={1.5} />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={remover}
              disabled={submitting}
              aria-label="Remover fetiche"
              className="hover:text-state-lost"
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <X size={14} strokeWidth={1.5} />}
            </Button>
          </>
        )}
      </div>

      {linha.cobra_por_pessoa && <div className="w-full"><AvisoPorPessoa /></div>}
    </li>
  )
}
