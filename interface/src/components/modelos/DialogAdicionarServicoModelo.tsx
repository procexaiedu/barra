"use client"

import { useMemo, useState } from "react"
import { Check, Loader2, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogBody, DialogCloseButton, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type {
  Duracao,
  DuracaoInput,
  Programa,
  ProgramaInput,
  ProgramaModeloVinculo,
} from "@/tipos/modelos"

type PrecosMap = Record<string, Record<string, string>>

export function DialogAdicionarServicoModelo({
  open,
  catalogo,
  duracoes,
  vinculados,
  onOpenChange,
  onCriarPrograma,
  onCriarDuracao,
  onVincular,
}: {
  open: boolean
  catalogo: Programa[]
  duracoes: Duracao[]
  vinculados: ProgramaModeloVinculo[]
  onOpenChange: (open: boolean) => void
  onCriarPrograma: (input: ProgramaInput) => Promise<Programa>
  onCriarDuracao: (input: DuracaoInput) => Promise<Duracao>
  onVincular: (programaId: string, duracaoId: string, preco: number) => Promise<void>
}) {
  const [programasSelecionados, setProgramasSelecionados] = useState<string[]>([])
  const [duracoesPorPrograma, setDuracoesPorPrograma] = useState<Record<string, string[]>>({})
  const [precos, setPrecos] = useState<PrecosMap>({})
  const [criandoPrograma, setCriandoPrograma] = useState(false)
  const [nomeProgramaNovo, setNomeProgramaNovo] = useState("")
  const [criandoDuracaoPara, setCriandoDuracaoPara] = useState<string | null>(null)
  const [nomeDuracaoNova, setNomeDuracaoNova] = useState("")
  const [salvandoInline, setSalvandoInline] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const vinculadosSet = useMemo(
    () => new Set(vinculados.map((v) => `${v.programa_id}:${v.duracao_id}`)),
    [vinculados],
  )

  const limpar = () => {
    setProgramasSelecionados([])
    setDuracoesPorPrograma({})
    setPrecos({})
    setCriandoPrograma(false)
    setNomeProgramaNovo("")
    setCriandoDuracaoPara(null)
    setNomeDuracaoNova("")
  }

  const fechar = () => {
    if (submitting) return
    limpar()
    onOpenChange(false)
  }

  const toggleServico = (id: string) => {
    if (programasSelecionados.includes(id)) {
      setProgramasSelecionados(programasSelecionados.filter((pid) => pid !== id))
      const nextDur = { ...duracoesPorPrograma }
      delete nextDur[id]
      setDuracoesPorPrograma(nextDur)
      const nextPrecos = { ...precos }
      delete nextPrecos[id]
      setPrecos(nextPrecos)
    } else {
      setProgramasSelecionados([...programasSelecionados, id])
    }
  }

  const toggleDuracao = (programaId: string, duracaoId: string) => {
    const atuais = duracoesPorPrograma[programaId] ?? []
    if (atuais.includes(duracaoId)) {
      setDuracoesPorPrograma({
        ...duracoesPorPrograma,
        [programaId]: atuais.filter((d) => d !== duracaoId),
      })
      const nextPrecos = { ...precos }
      if (nextPrecos[programaId]) {
        const subset = { ...nextPrecos[programaId] }
        delete subset[duracaoId]
        nextPrecos[programaId] = subset
      }
      setPrecos(nextPrecos)
    } else {
      setDuracoesPorPrograma({
        ...duracoesPorPrograma,
        [programaId]: [...atuais, duracaoId],
      })
    }
  }

  const setPreco = (programaId: string, duracaoId: string, valor: string) => {
    setPrecos({
      ...precos,
      [programaId]: { ...(precos[programaId] ?? {}), [duracaoId]: valor },
    })
  }

  const confirmarPrograma = async () => {
    const nome = nomeProgramaNovo.trim()
    if (!nome) return
    if (catalogo.some((p) => p.nome.toLowerCase() === nome.toLowerCase())) {
      toast.error("Já existe um serviço com esse nome")
      return
    }
    setSalvandoInline(true)
    try {
      const novo = await onCriarPrograma({ nome })
      setProgramasSelecionados((atuais) => [...atuais, novo.id])
      setNomeProgramaNovo("")
      setCriandoPrograma(false)
      toast.success("Serviço criado")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao criar serviço")
    } finally {
      setSalvandoInline(false)
    }
  }

  const confirmarDuracao = async (programaId: string) => {
    const nome = nomeDuracaoNova.trim()
    if (!nome) return
    if (duracoes.some((d) => d.nome.toLowerCase() === nome.toLowerCase())) {
      toast.error("Já existe uma duração com esse nome")
      return
    }
    setSalvandoInline(true)
    try {
      const nova = await onCriarDuracao({ nome, ordem: duracoes.length })
      setDuracoesPorPrograma((atuais) => ({
        ...atuais,
        [programaId]: [...(atuais[programaId] ?? []), nova.id],
      }))
      setNomeDuracaoNova("")
      setCriandoDuracaoPara(null)
      toast.success("Duração criada")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao criar duração")
    } finally {
      setSalvandoInline(false)
    }
  }

  const paresValidos = useMemo(() => {
    const lista: { programaId: string; duracaoId: string; preco: number }[] = []
    for (const pid of programasSelecionados) {
      for (const did of duracoesPorPrograma[pid] ?? []) {
        const raw = precos[pid]?.[did]?.trim() ?? ""
        if (!raw) continue
        const preco = Number(raw.replace(",", "."))
        if (!isNaN(preco) && preco >= 0) {
          lista.push({ programaId: pid, duracaoId: did, preco })
        }
      }
    }
    return lista
  }, [duracoesPorPrograma, precos, programasSelecionados])

  const totalPares = useMemo(() => {
    let n = 0
    for (const pid of programasSelecionados) {
      n += (duracoesPorPrograma[pid] ?? []).length
    }
    return n
  }, [duracoesPorPrograma, programasSelecionados])

  const podeSalvar =
    programasSelecionados.length > 0 &&
    totalPares > 0 &&
    paresValidos.length === totalPares

  const submit = async () => {
    if (!podeSalvar) return
    setSubmitting(true)
    const resultados = await Promise.allSettled(
      paresValidos.map((p) => onVincular(p.programaId, p.duracaoId, p.preco)),
    )
    const sucesso = resultados.filter((r) => r.status === "fulfilled").length
    const falhas = resultados.length - sucesso
    setSubmitting(false)
    if (sucesso > 0) {
      toast.success(`${sucesso} ${sucesso === 1 ? "linha adicionada" : "linhas adicionadas"}`)
    }
    if (falhas > 0) {
      toast.error(`${falhas} ${falhas === 1 ? "linha falhou" : "linhas falharam"} ao salvar`)
    }
    if (falhas === 0) {
      limpar()
      onOpenChange(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !submitting && (value ? onOpenChange(true) : fechar())}>
      <DialogContent size="md">
        <DialogHeader className="items-start justify-between gap-4">
          <div>
            <DialogTitle className="text-lg font-semibold">Adicionar serviço</DialogTitle>
            <DialogDescription>
              Escolha quais serviços a modelo oferece, em quais durações, e o preço de cada um.
            </DialogDescription>
          </div>
          <DialogCloseButton />
        </DialogHeader>

        <DialogBody className="space-y-6">
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">Serviços</h3>
              {!criandoPrograma && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setCriandoPrograma(true)}
                  disabled={submitting}
                >
                  <Plus size={13} strokeWidth={1.5} />
                  Novo serviço
                </Button>
              )}
            </div>

            {catalogo.length === 0 && !criandoPrograma ? (
              <p className="rounded-lg border border-dashed border-border bg-muted px-4 py-6 text-center text-sm text-text-muted">
                Nenhum serviço cadastrado. Crie o primeiro.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {catalogo.map((programa) => (
                  <Chip
                    key={programa.id}
                    selected={programasSelecionados.includes(programa.id)}
                    onClick={() => toggleServico(programa.id)}
                    disabled={submitting}
                  >
                    {programa.nome}
                  </Chip>
                ))}
              </div>
            )}

            {criandoPrograma && (
              <div className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-muted p-2">
                <Input
                  value={nomeProgramaNovo}
                  onChange={(e) => setNomeProgramaNovo(e.target.value)}
                  placeholder="Ex.: Beijo grego"
                  autoFocus
                  className="h-9 flex-1 bg-input text-sm"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      confirmarPrograma()
                    }
                    if (e.key === "Escape") {
                      setCriandoPrograma(false)
                      setNomeProgramaNovo("")
                    }
                  }}
                />
                <Button
                  variant="primary"
                  size="sm"
                  onClick={confirmarPrograma}
                  disabled={!nomeProgramaNovo.trim() || salvandoInline}
                >
                  {salvandoInline ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} strokeWidth={2} />}
                  Criar
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setCriandoPrograma(false)
                    setNomeProgramaNovo("")
                  }}
                  disabled={salvandoInline}
                >
                  Cancelar
                </Button>
              </div>
            )}
          </section>

          {programasSelecionados.length > 0 && (
            <section className="space-y-4">
              <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
                Durações e preços
              </h3>

              {programasSelecionados.map((pid) => {
                const programa = catalogo.find((p) => p.id === pid)
                if (!programa) return null
                const duracoesMarcadas = duracoesPorPrograma[pid] ?? []
                const editandoDuracao = criandoDuracaoPara === pid

                return (
                  <div key={pid} className="overflow-hidden rounded-md border border-border">
                    <div className="flex items-center justify-between gap-3 border-b border-border bg-muted px-4 py-2.5">
                      <h4 className="text-sm font-semibold text-text-primary">{programa.nome}</h4>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => toggleServico(pid)}
                        aria-label={`Remover ${programa.nome}`}
                        disabled={submitting}
                      >
                        <X size={13} strokeWidth={1.5} />
                      </Button>
                    </div>

                    <div className="space-y-3 px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        {duracoes.map((d) => {
                          const jaExiste = vinculadosSet.has(`${pid}:${d.id}`)
                          return (
                            <Chip
                              key={d.id}
                              selected={duracoesMarcadas.includes(d.id)}
                              onClick={() => !jaExiste && toggleDuracao(pid, d.id)}
                              disabled={submitting || jaExiste}
                              hint={jaExiste ? "já cadastrada" : undefined}
                            >
                              {d.nome}
                            </Chip>
                          )
                        })}
                        {!editandoDuracao && (
                          <button
                            type="button"
                            onClick={() => setCriandoDuracaoPara(pid)}
                            disabled={submitting}
                            className="inline-flex items-center gap-1 rounded-full border border-dashed border-border bg-transparent px-3 py-1 text-xs font-medium text-text-muted transition-colors hover:border-gold-500 hover:text-text-primary disabled:opacity-50"
                          >
                            <Plus size={12} strokeWidth={1.5} />
                            Nova duração
                          </button>
                        )}
                      </div>

                      {editandoDuracao && (
                        <div className="flex items-center gap-2 rounded-lg border border-border bg-muted p-2">
                          <Input
                            value={nomeDuracaoNova}
                            onChange={(e) => setNomeDuracaoNova(e.target.value)}
                            placeholder="Ex.: 45 min"
                            autoFocus
                            className="h-9 flex-1 bg-input text-sm"
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                e.preventDefault()
                                confirmarDuracao(pid)
                              }
                              if (e.key === "Escape") {
                                setCriandoDuracaoPara(null)
                                setNomeDuracaoNova("")
                              }
                            }}
                          />
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => confirmarDuracao(pid)}
                            disabled={!nomeDuracaoNova.trim() || salvandoInline}
                          >
                            {salvandoInline ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} strokeWidth={2} />}
                            Criar
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setCriandoDuracaoPara(null)
                              setNomeDuracaoNova("")
                            }}
                            disabled={salvandoInline}
                          >
                            Cancelar
                          </Button>
                        </div>
                      )}

                      {duracoesMarcadas.length > 0 && (
                        <div className="space-y-2 border-t border-border pt-3">
                          {duracoesMarcadas.map((did) => {
                            const dur = duracoes.find((d) => d.id === did)
                            if (!dur) return null
                            const valor = precos[pid]?.[did] ?? ""
                            return (
                              <div key={did} className="flex items-center justify-between gap-3">
                                <span className="text-sm text-text-secondary">{dur.nome}</span>
                                <div className="flex items-center gap-2">
                                  <span className="text-xs text-text-muted">R$</span>
                                  <Input
                                    type="number"
                                    min={0}
                                    step={50}
                                    value={valor}
                                    onChange={(e) => setPreco(pid, did, e.target.value)}
                                    placeholder="0,00"
                                    className="h-9 w-32 bg-input font-mono text-sm tabular-nums"
                                  />
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </section>
          )}
        </DialogBody>

        <DialogFooter className="justify-between gap-3 bg-muted">
          <span className="text-xs text-text-muted">
            {totalPares === 0
              ? "Selecione ao menos um serviço e duração."
              : paresValidos.length === totalPares
                ? `${totalPares} ${totalPares === 1 ? "linha pronta" : "linhas prontas"}`
                : `${totalPares - paresValidos.length} ${totalPares - paresValidos.length === 1 ? "preço pendente" : "preços pendentes"}`}
          </span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={fechar} disabled={submitting}>
              Cancelar
            </Button>
            <Button variant="primary" onClick={submit} disabled={!podeSalvar || submitting}>
              {submitting && <Loader2 className="animate-spin" />}
              Adicionar
              {totalPares > 0 ? ` ${totalPares}` : ""}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Chip({
  selected,
  disabled,
  hint,
  onClick,
  children,
}: {
  selected: boolean
  disabled?: boolean
  hint?: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={selected}
      title={hint}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors cursor-pointer",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        selected
          ? "border-gold-500 bg-gold-500/10 text-text-primary"
          : "border-border bg-card text-text-secondary hover:border-text-muted hover:text-text-primary",
      )}
    >
      {selected && <Check size={12} strokeWidth={2} />}
      {children}
      {hint && !selected && <span className="text-[10px] uppercase tracking-wider text-text-muted">· {hint}</span>}
    </button>
  )
}
