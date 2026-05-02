"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FotoPerfil } from "@/components/modelos/FotoPerfil"
import { ProgramasModelo } from "@/components/modelos/ProgramasModelo"
import { TipoChecks } from "@/components/modelos/DialogCriarModelo"
import type { Duracao, ModeloDetalhe, PatchModeloInput, Programa, ProgramaModeloVinculo } from "@/tipos/modelos"

export function AbaPerfil({
  modelo,
  catalogo,
  duracoes,
  programasVinculados,
  onDirtyChange,
  onSalvar,
  onVincularPrograma,
  onAtualizarPrecoPrograma,
  onDesvincularPrograma,
  onTrocarNumero,
  onConectar,
  onDesparear,
  onUploadPerfil,
  onRemoverFoto,
}: {
  modelo: ModeloDetalhe
  catalogo: Programa[]
  duracoes: Duracao[]
  programasVinculados: ProgramaModeloVinculo[]
  onDirtyChange: (dirty: boolean) => void
  onSalvar: (input: PatchModeloInput) => Promise<void>
  onVincularPrograma: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onAtualizarPrecoPrograma: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onDesvincularPrograma: (programaId: string, duracaoId: string) => Promise<void>
  onTrocarNumero: (numero: string) => void
  onConectar: () => void
  onDesparear: () => void
  onUploadPerfil: () => void
  onRemoverFoto: () => Promise<void>
}) {
  const [identidade, setIdentidade] = useState({ nome: modelo.nome, idade: modelo.idade })
  const [whats, setWhats] = useState({ numero_whatsapp: modelo.numero_whatsapp })
  const [repasse, setRepasse] = useState({
    percentual_repasse: modelo.percentual_repasse === null ? "" : String(modelo.percentual_repasse),
    chave_pix: modelo.chave_pix ?? "",
    titular_chave: modelo.titular_chave ?? "",
  })
  const [atendimento, setAtendimento] = useState({
    localizacao_operacional: modelo.localizacao_operacional ?? "",
    idiomas: modelo.idiomas.join(", "),
    tipo_atendimento_aceito: modelo.tipo_atendimento_aceito,
  })
  const [submitting, setSubmitting] = useState<string | null>(null)

  const dirtyIdentidade = identidade.nome !== modelo.nome || identidade.idade !== modelo.idade
  const dirtyWhats = whats.numero_whatsapp !== modelo.numero_whatsapp
  const percentual = repasse.percentual_repasse === "" ? null : Number(repasse.percentual_repasse)
  const dirtyRepasse =
    percentual !== modelo.percentual_repasse ||
    repasse.chave_pix !== (modelo.chave_pix ?? "") ||
    repasse.titular_chave !== (modelo.titular_chave ?? "")
  const idiomasArray = useMemo(() => atendimento.idiomas.split(",").map((i) => i.trim()).filter(Boolean), [atendimento.idiomas])
  const dirtyAtendimento =
    atendimento.localizacao_operacional !== (modelo.localizacao_operacional ?? "") ||
    atendimento.idiomas !== modelo.idiomas.join(", ") ||
    atendimento.tipo_atendimento_aceito.join("|") !== modelo.tipo_atendimento_aceito.join("|")
  const anyDirty = dirtyIdentidade || dirtyWhats || dirtyRepasse || dirtyAtendimento

  useEffect(() => {
    const timer = setTimeout(() => onDirtyChange(anyDirty), 0)
    return () => clearTimeout(timer)
  }, [anyDirty, onDirtyChange])

  const salvar = async (key: string, input: PatchModeloInput, ok: string) => {
    setSubmitting(key)
    try {
      await onSalvar(input)
      toast.success(ok)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSubmitting(null)
    }
  }

  const identidadeValida = identidade.nome.trim().length > 0 && identidade.nome.length <= 100 && identidade.idade > 0
  const whatsappValido = /^\+55\d{10,11}$/.test(whats.numero_whatsapp)
  const repasseValido = percentual === null || (percentual >= 0 && percentual <= 100)
  const atendimentoValido = idiomasArray.length > 0 && atendimento.tipo_atendimento_aceito.length > 0

  return (
    <div className="space-y-5">
      <Card title="Identidade">
        <div className="mb-5 flex items-center gap-4">
          <FotoPerfil url={modelo.foto_perfil_url} nome={modelo.nome} size="lg" />
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" onClick={onUploadPerfil}>Alterar foto</Button>
            {modelo.foto_perfil_url && (
              <Button
                variant="ghost"
                onClick={async () => {
                  await onRemoverFoto()
                  toast.success("Foto de perfil removida")
                }}
              >
                <Trash2 size={16} strokeWidth={1.5} />
                Remover foto
              </Button>
            )}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Campo label="Nome">
            <Input value={identidade.nome} onChange={(e) => setIdentidade({ ...identidade, nome: e.target.value })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Idade">
            <Input type="number" value={identidade.idade || ""} onChange={(e) => setIdentidade({ ...identidade, idade: Number(e.target.value) })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Situação">
            <select disabled value={modelo.status} className="h-10 rounded-lg border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-muted">
              <option value="ativa">Ativa</option>
              <option value="pausada">Pausada</option>
              <option value="inativa">Inativa</option>
            </select>
          </Campo>
        </div>
        <Salvar
          dirty={dirtyIdentidade}
          disabled={!identidadeValida}
          submitting={submitting === "identidade"}
          label="Salvar identidade"
          onClick={() => salvar("identidade", { nome: identidade.nome.trim(), idade: identidade.idade }, "Identidade atualizada")}
        />
      </Card>

      <Card title="Contato">
        <Campo label="Número de WhatsApp">
          <Input value={whats.numero_whatsapp} onChange={(e) => setWhats({ numero_whatsapp: e.target.value })} className="h-10 bg-input" />
        </Campo>
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-text-secondary">
          <span className={modelo.evolution_instance_id ? "text-text-muted" : "text-state-handoff"}>
            {modelo.evolution_instance_id ? "WhatsApp pronto" : "WhatsApp pendente"}
          </span>
          {modelo.evolution_instance_id ? (
            <>
              <Button variant="secondary" size="sm" onClick={onConectar}>Trocar conexão</Button>
              <Button variant="danger" size="sm" onClick={onDesparear}>Remover conexão</Button>
            </>
          ) : (
            <Button variant="primary" size="sm" onClick={onConectar}>Conectar WhatsApp</Button>
          )}
        </div>
        <Salvar
          dirty={dirtyWhats}
          disabled={!whatsappValido}
          submitting={submitting === "whatsapp"}
          label="Salvar WhatsApp"
          onClick={() => {
            if (modelo.evolution_instance_id) onTrocarNumero(whats.numero_whatsapp)
            else salvar("whatsapp", { numero_whatsapp: whats.numero_whatsapp }, "WhatsApp atualizado")
          }}
        />
      </Card>

      <ProgramasModelo
        catalogo={catalogo}
        duracoes={duracoes}
        vinculados={programasVinculados}
        onVincular={onVincularPrograma}
        onAtualizarPreco={onAtualizarPrecoPrograma}
        onDesvincular={onDesvincularPrograma}
      />

      <Card title="Repasse e Pix">
        <div className="grid gap-4 sm:grid-cols-2">
          <Campo label="Comissão da agência (%)">
            <Input type="number" min={0} max={100} value={repasse.percentual_repasse} onChange={(e) => setRepasse({ ...repasse, percentual_repasse: e.target.value })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Pix">
            <Input value={repasse.chave_pix} onChange={(e) => setRepasse({ ...repasse, chave_pix: e.target.value })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Nome no Pix">
            <Input value={repasse.titular_chave} onChange={(e) => setRepasse({ ...repasse, titular_chave: e.target.value })} className="h-10 bg-input" />
          </Campo>
        </div>
        <Salvar
          dirty={dirtyRepasse}
          disabled={!repasseValido}
          submitting={submitting === "repasse"}
          label="Salvar repasse"
          onClick={() => salvar("repasse", {
            percentual_repasse: percentual,
            chave_pix: repasse.chave_pix.trim() || null,
            titular_chave: repasse.titular_chave.trim() || null,
          }, "Repasse atualizado")}
        />
      </Card>

      <Card title="Atendimento">
        <div className="grid gap-4 sm:grid-cols-2">
          <Campo label="Bairro ou região">
            <Input value={atendimento.localizacao_operacional} onChange={(e) => setAtendimento({ ...atendimento, localizacao_operacional: e.target.value })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Idiomas">
            <Input value={atendimento.idiomas} onChange={(e) => setAtendimento({ ...atendimento, idiomas: e.target.value })} className="h-10 bg-input" />
          </Campo>
          <div className="sm:col-span-2">
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">Atende em</p>
            <TipoChecks value={atendimento.tipo_atendimento_aceito} onChange={(tipo_atendimento_aceito) => setAtendimento({ ...atendimento, tipo_atendimento_aceito })} />
          </div>
        </div>
        <Salvar
          dirty={dirtyAtendimento}
          disabled={!atendimentoValido}
          submitting={submitting === "atendimento"}
          label="Salvar atendimento"
          onClick={() => salvar("atendimento", {
            localizacao_operacional: atendimento.localizacao_operacional.trim() || null,
            idiomas: idiomasArray,
            tipo_atendimento_aceito: atendimento.tipo_atendimento_aceito,
          }, "Atendimento atualizado")}
        />
      </Card>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-4 text-base font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  )
}

function Campo({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
      {label}
      {children}
    </label>
  )
}

function Salvar({
  dirty,
  disabled,
  submitting,
  label,
  onClick,
}: {
  dirty: boolean
  disabled: boolean
  submitting: boolean
  label: string
  onClick: () => void
}) {
  if (!dirty) return null
  return (
    <div className="mt-5 flex justify-end border-t border-border pt-4">
      <Button variant="secondary" onClick={onClick} disabled={disabled || submitting}>
        {submitting && <Loader2 className="animate-spin" />}
        {label}
      </Button>
    </div>
  )
}
