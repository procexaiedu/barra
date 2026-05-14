"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FotoPerfil } from "@/components/modelos/FotoPerfil"
import { ProgramasModelo } from "@/components/modelos/ProgramasModelo"
import { TipoChecks } from "@/components/modelos/DialogCriarModelo"
import { CampoLocalAutocomplete } from "@/components/modelos/CampoLocalAutocomplete"
import { deE164BR, extrairDigitosTelefone, formatarTelefoneBR, paraE164BR } from "@/lib/telefone"
import type {
  Duracao,
  DuracaoInput,
  ModeloDetalhe,
  PatchModeloInput,
  Programa,
  ProgramaInput,
  ProgramaModeloVinculo,
} from "@/tipos/modelos"

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
  onCriarPrograma,
  onCriarDuracao,
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
  onCriarPrograma: (input: ProgramaInput) => Promise<Programa>
  onCriarDuracao: (input: DuracaoInput) => Promise<Duracao>
  onTrocarNumero: (numero: string) => void
  onConectar: () => void
  onDesparear: () => void
  onUploadPerfil: () => void
  onRemoverFoto: () => Promise<void>
}) {
  const [identidade, setIdentidade] = useState({ nome: modelo.nome, idade: modelo.idade })
  const [numeroDigitos, setNumeroDigitos] = useState(() => deE164BR(modelo.numero_whatsapp))
  const [repasse, setRepasse] = useState({
    percentual_repasse: modelo.percentual_repasse === null ? "" : String(modelo.percentual_repasse),
    chave_pix: modelo.chave_pix ?? "",
    titular_chave: modelo.titular_chave ?? "",
  })
  const [atendimento, setAtendimento] = useState({
    localizacao_operacional: modelo.localizacao_operacional ?? "",
    endereco_formatado: modelo.endereco_formatado,
    latitude: modelo.latitude,
    longitude: modelo.longitude,
    place_id: modelo.place_id,
    idiomas: modelo.idiomas.join(", "),
    tipo_atendimento_aceito: modelo.tipo_atendimento_aceito,
  })
  const [submitting, setSubmitting] = useState<string | null>(null)

  const dirtyIdentidade = identidade.nome !== modelo.nome || identidade.idade !== modelo.idade
  const dirtyWhats = paraE164BR(numeroDigitos) !== modelo.numero_whatsapp
  const percentual = repasse.percentual_repasse === "" ? null : Number(repasse.percentual_repasse)
  const dirtyRepasse =
    percentual !== modelo.percentual_repasse ||
    repasse.chave_pix !== (modelo.chave_pix ?? "") ||
    repasse.titular_chave !== (modelo.titular_chave ?? "")
  const idiomasArray = useMemo(() => atendimento.idiomas.split(",").map((i) => i.trim()).filter(Boolean), [atendimento.idiomas])
  const dirtyAtendimento =
    atendimento.localizacao_operacional !== (modelo.localizacao_operacional ?? "") ||
    atendimento.endereco_formatado !== modelo.endereco_formatado ||
    atendimento.place_id !== modelo.place_id ||
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
  const whatsappValido = /^\d{10,11}$/.test(numeroDigitos)
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
        <div className="grid gap-5 sm:grid-cols-2">
          <Campo label="Nome">
            <Input value={identidade.nome} onChange={(e) => setIdentidade({ ...identidade, nome: e.target.value })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Idade">
            <Input type="number" value={identidade.idade || ""} onChange={(e) => setIdentidade({ ...identidade, idade: Number(e.target.value) })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Situação">
            <select disabled value={modelo.status} className="h-10 rounded-md border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-muted disabled:cursor-not-allowed disabled:opacity-70">
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
          <Input
            value={formatarTelefoneBR(numeroDigitos)}
            placeholder="(21) 98765-4321"
            onChange={(e) => setNumeroDigitos(extrairDigitosTelefone(e.target.value))}
            className="h-10 bg-input"
          />
        </Campo>
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-text-secondary">
          <span
            className={
              modelo.evolution_status === "conectado"
                ? "text-text-muted"
                : modelo.evolution_status === "pareando"
                  ? "text-state-info"
                  : "text-state-handoff"
            }
          >
            {modelo.evolution_status === "conectado"
              ? "WhatsApp pronto"
              : modelo.evolution_status === "pareando"
                ? "Aguardando pareamento"
                : "WhatsApp pendente"}
          </span>
          {modelo.evolution_status === "conectado" ? (
            <>
              <Button variant="secondary" size="sm" onClick={onConectar}>Trocar conexão</Button>
              <Button variant="danger" size="sm" onClick={onDesparear}>Remover conexão</Button>
            </>
          ) : modelo.evolution_status === "pareando" ? (
            <>
              <Button variant="secondary" size="sm" onClick={onConectar}>Reabrir QR</Button>
              <Button variant="danger" size="sm" onClick={onDesparear}>Cancelar</Button>
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
            const numeroE164 = paraE164BR(numeroDigitos)
            if (modelo.evolution_status === "conectado") onTrocarNumero(numeroE164)
            else salvar("whatsapp", { numero_whatsapp: numeroE164 }, "WhatsApp atualizado")
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
        onCriarPrograma={onCriarPrograma}
        onCriarDuracao={onCriarDuracao}
      />

      <Card title="Repasse e Pix">
        <div className="grid gap-5 sm:grid-cols-2">
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
        <div className="grid gap-5 sm:grid-cols-2">
          <Campo label="Endereço de atendimento">
            <CampoLocalAutocomplete
              valorInicial={atendimento.localizacao_operacional}
              enderecoFormatadoAtual={atendimento.endereco_formatado}
              onSelecionar={(local) =>
                setAtendimento((a) => ({
                  ...a,
                  localizacao_operacional: local.localizacao_curta,
                  endereco_formatado: local.endereco_formatado,
                  latitude: local.latitude,
                  longitude: local.longitude,
                  place_id: local.place_id,
                }))
              }
              onLimpar={() =>
                setAtendimento((a) => ({
                  ...a,
                  localizacao_operacional: "",
                  endereco_formatado: null,
                  latitude: null,
                  longitude: null,
                  place_id: null,
                }))
              }
            />
          </Campo>
          <Campo label="Idiomas">
            <Input value={atendimento.idiomas} onChange={(e) => setAtendimento({ ...atendimento, idiomas: e.target.value })} className="h-10 bg-input" />
          </Campo>
          <div className="sm:col-span-2">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-text-secondary">Atende em</p>
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
            endereco_formatado: atendimento.endereco_formatado,
            latitude: atendimento.latitude,
            longitude: atendimento.longitude,
            place_id: atendimento.place_id,
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
      <h2 className="mb-5 text-base font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  )
}

function Campo({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-2.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-text-secondary">
      <span className="leading-none">{label}</span>
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
