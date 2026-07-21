"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FotoPerfil } from "@/components/modelos/FotoPerfil"
import { ProgramasModelo } from "@/components/modelos/ProgramasModelo"
import { TipoChecks } from "@/components/modelos/DialogCriarModelo"
import { CampoLocalAutocomplete } from "@/components/comum/CampoLocalAutocomplete"
import { deE164BR, extrairDigitosTelefone, formatarTelefoneBR, paraE164BR } from "@/lib/telefone"
import { PERFIS_FISICOS, PERFIL_FISICO_LABEL } from "@/lib/perfilFisico"
import {
  CORES_CABELO,
  CORES_PELE,
  COR_CABELO_LABEL,
  COR_PELE_LABEL,
  SIGNOS,
  SIGNO_LABEL,
} from "@/lib/cadastroModelo"
import { NIVEIS, NIVEL_LABEL } from "@/lib/nivel"
import { cpfValido, formatarCpf, normalizarCpf } from "@/lib/cpf"
import { formatarRg, normalizarRg } from "@/lib/rg"
import type {
  Duracao,
  DuracaoInput,
  Fetiche,
  FeticheInput,
  FeticheModeloVinculo,
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
  fetichesVinculados,
  catalogoFetiches,
  onDirtyChange,
  onSalvar,
  onVincularPrograma,
  onAtualizarPrecoPrograma,
  onDesvincularPrograma,
  onCriarPrograma,
  onCriarDuracao,
  onVincularFetiche,
  onAtualizarFetiche,
  onDesvincularFetiche,
  onCriarFetiche,
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
  fetichesVinculados: FeticheModeloVinculo[]
  catalogoFetiches: Fetiche[]
  onDirtyChange: (dirty: boolean) => void
  onSalvar: (input: PatchModeloInput) => Promise<void>
  onVincularPrograma: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onAtualizarPrecoPrograma: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onDesvincularPrograma: (programaId: string, duracaoId: string) => Promise<void>
  onCriarPrograma: (input: ProgramaInput) => Promise<Programa>
  onCriarDuracao: (input: DuracaoInput) => Promise<Duracao>
  onVincularFetiche: (feticheId: string, pago: boolean) => Promise<void>
  onAtualizarFetiche: (feticheId: string, pago: boolean) => Promise<void>
  onDesvincularFetiche: (feticheId: string) => Promise<void>
  onCriarFetiche: (input: FeticheInput) => Promise<Fetiche>
  onTrocarNumero: (numero: string) => void
  onConectar: () => void
  onDesparear: () => void
  onUploadPerfil: () => void
  onRemoverFoto: () => Promise<void>
}) {
  const [identidade, setIdentidade] = useState({
    nome: modelo.nome,
    idade: modelo.idade,
    nivel: modelo.nivel ?? "",
    signo: modelo.signo ?? "",
  })
  const [numeroDigitos, setNumeroDigitos] = useState(() => deE164BR(modelo.numero_whatsapp))
  const [repasse, setRepasse] = useState({
    percentual_repasse: modelo.percentual_repasse === null ? "" : String(modelo.percentual_repasse),
    chave_pix: modelo.chave_pix ?? "",
    titular_chave: modelo.titular_chave ?? "",
  })
  const [atendimento, setAtendimento] = useState({
    localizacao_operacional: modelo.localizacao_operacional ?? "",
    endereco_formatado: modelo.endereco_formatado,
    nome_local: modelo.nome_local,
    latitude: modelo.latitude,
    longitude: modelo.longitude,
    place_id: modelo.place_id,
    idiomas: modelo.idiomas.join(", "),
    tipo_atendimento_aceito: modelo.tipo_atendimento_aceito,
  })
  const [fisico, setFisico] = useState({
    tipo_fisico: modelo.tipo_fisico ?? "",
    cor_pele: modelo.cor_pele ?? "",
    cor_cabelo: modelo.cor_cabelo ?? "",
    altura_cm: modelo.altura_cm as number | null,
    tamanho_pe: modelo.tamanho_pe as number | null,
    peso_kg: modelo.peso_kg as number | null,
    cintura_cm: modelo.cintura_cm as number | null,
  })
  const [dados, setDados] = useState({
    rg: formatarRg(modelo.rg ?? ""),
    cpf: formatarCpf(modelo.cpf ?? ""),
    endereco_residencial_formatado: modelo.endereco_residencial_formatado,
    place_id_residencial: modelo.place_id_residencial,
    instagram: modelo.instagram ?? "",
    email: modelo.email ?? "",
  })
  const [submitting, setSubmitting] = useState<string | null>(null)

  const dirtyIdentidade =
    identidade.nome !== modelo.nome ||
    identidade.idade !== modelo.idade ||
    (identidade.nivel || null) !== modelo.nivel ||
    (identidade.signo || null) !== modelo.signo
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
    atendimento.nome_local !== modelo.nome_local ||
    atendimento.place_id !== modelo.place_id ||
    atendimento.idiomas !== modelo.idiomas.join(", ") ||
    atendimento.tipo_atendimento_aceito.join("|") !== modelo.tipo_atendimento_aceito.join("|")
  const dirtyFisico =
    (fisico.tipo_fisico || null) !== modelo.tipo_fisico ||
    (fisico.cor_pele || null) !== modelo.cor_pele ||
    (fisico.cor_cabelo || null) !== modelo.cor_cabelo ||
    fisico.altura_cm !== modelo.altura_cm ||
    fisico.tamanho_pe !== modelo.tamanho_pe ||
    fisico.peso_kg !== modelo.peso_kg ||
    fisico.cintura_cm !== modelo.cintura_cm
  const cpfDigitos = normalizarCpf(dados.cpf)
  const rgNormalizado = normalizarRg(dados.rg)
  const dirtyDados =
    rgNormalizado !== (modelo.rg ?? "") ||
    cpfDigitos !== (modelo.cpf ?? "") ||
    dados.endereco_residencial_formatado !== modelo.endereco_residencial_formatado ||
    dados.place_id_residencial !== modelo.place_id_residencial ||
    (dados.instagram.trim() || null) !== modelo.instagram ||
    (dados.email.trim() || null) !== modelo.email
  const anyDirty = dirtyIdentidade || dirtyWhats || dirtyRepasse || dirtyAtendimento || dirtyFisico || dirtyDados

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
  const cpfCadastroValido = cpfDigitos === "" || cpfValido(dados.cpf)
  const alturaValida =
    fisico.altura_cm === null || (fisico.altura_cm >= 100 && fisico.altura_cm <= 230)
  const peValido =
    fisico.tamanho_pe === null || (fisico.tamanho_pe >= 28 && fisico.tamanho_pe <= 50)
  const pesoValido =
    fisico.peso_kg === null || (fisico.peso_kg >= 30 && fisico.peso_kg <= 200)
  const cinturaValida =
    fisico.cintura_cm === null || (fisico.cintura_cm >= 40 && fisico.cintura_cm <= 120)
  const emailTrim = dados.email.trim()
  const emailValido = emailTrim === "" || /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(emailTrim)
  const fisicoValido = alturaValida && peValido && pesoValido && cinturaValida
  const dadosValido = cpfCadastroValido && emailValido

  return (
    <div className="flex flex-col gap-4">
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
            <select disabled value={modelo.status} className="h-10 rounded-lg border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-muted disabled:cursor-not-allowed disabled:opacity-70">
              <option value="ativa">Ativa</option>
              <option value="pausada">Pausada</option>
              <option value="inativa">Inativa</option>
            </select>
          </Campo>
          <Campo label="Nível">
            <select
              value={identidade.nivel}
              onChange={(e) => setIdentidade({ ...identidade, nivel: e.target.value })}
              className="h-10 rounded-lg border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <option value="">Sem classificação</option>
              {NIVEIS.map((nivel) => (
                <option key={nivel} value={nivel}>
                  {NIVEL_LABEL[nivel]}
                </option>
              ))}
            </select>
          </Campo>
          <Campo label="Signo">
            <select
              value={identidade.signo}
              onChange={(e) => setIdentidade({ ...identidade, signo: e.target.value })}
              className="h-10 rounded-lg border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <option value="">Não informado</option>
              {SIGNOS.map((slug) => (
                <option key={slug} value={slug}>
                  {SIGNO_LABEL[slug]}
                </option>
              ))}
            </select>
          </Campo>
        </div>
        <Salvar
          dirty={dirtyIdentidade}
          disabled={!identidadeValida}
          submitting={submitting === "identidade"}
          label="Salvar identidade"
          onClick={() => salvar("identidade", {
            nome: identidade.nome.trim(),
            idade: identidade.idade,
            nivel: (identidade.nivel || null) as PatchModeloInput["nivel"],
            signo: (identidade.signo || null) as PatchModeloInput["signo"],
          }, "Identidade atualizada")}
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

      <Card title="Características físicas">
        <div className="grid gap-5 sm:grid-cols-2">
          <Campo label="Perfil físico">
            <select
              value={fisico.tipo_fisico}
              onChange={(e) => setFisico({ ...fisico, tipo_fisico: e.target.value })}
              className="h-10 rounded-lg border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <option value="">Não classificada</option>
              {PERFIS_FISICOS.map((slug) => (
                <option key={slug} value={slug}>
                  {PERFIL_FISICO_LABEL[slug]}
                </option>
              ))}
            </select>
          </Campo>
          <Campo label="Cor de pele">
            <select
              value={fisico.cor_pele}
              onChange={(e) => setFisico({ ...fisico, cor_pele: e.target.value })}
              className="h-10 rounded-lg border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <option value="">Não informada</option>
              {CORES_PELE.map((slug) => (
                <option key={slug} value={slug}>
                  {COR_PELE_LABEL[slug]}
                </option>
              ))}
            </select>
          </Campo>
          <Campo label="Cor de cabelo">
            <select
              value={fisico.cor_cabelo}
              onChange={(e) => setFisico({ ...fisico, cor_cabelo: e.target.value })}
              className="h-10 rounded-lg border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <option value="">Não informada</option>
              {CORES_CABELO.map((slug) => (
                <option key={slug} value={slug}>
                  {COR_CABELO_LABEL[slug]}
                </option>
              ))}
            </select>
          </Campo>
          <Campo label="Altura (cm)">
            <Input
              type="number"
              min={100}
              max={230}
              value={fisico.altura_cm ?? ""}
              onChange={(e) =>
                setFisico({ ...fisico, altura_cm: e.target.value === "" ? null : Number(e.target.value) })
              }
              className="h-10 bg-input"
            />
            {fisico.altura_cm !== null && !alturaValida && (
              <span className="text-[11px] normal-case tracking-normal text-state-lost">Altura entre 100 e 230 cm</span>
            )}
          </Campo>
          <Campo label="Peso (kg)">
            <Input
              type="number"
              min={30}
              max={200}
              step="0.1"
              value={fisico.peso_kg ?? ""}
              onChange={(e) =>
                setFisico({ ...fisico, peso_kg: e.target.value === "" ? null : Number(e.target.value) })
              }
              className="h-10 bg-input"
            />
            {fisico.peso_kg !== null && !pesoValido && (
              <span className="text-[11px] normal-case tracking-normal text-state-lost">Peso entre 30 e 200 kg</span>
            )}
          </Campo>
          <Campo label="Cintura (cm)">
            <Input
              type="number"
              min={40}
              max={120}
              value={fisico.cintura_cm ?? ""}
              onChange={(e) =>
                setFisico({ ...fisico, cintura_cm: e.target.value === "" ? null : Number(e.target.value) })
              }
              className="h-10 bg-input"
            />
            {fisico.cintura_cm !== null && !cinturaValida && (
              <span className="text-[11px] normal-case tracking-normal text-state-lost">Cintura entre 40 e 120 cm</span>
            )}
          </Campo>
          <Campo label="Tamanho do pé">
            <Input
              type="number"
              min={28}
              max={50}
              value={fisico.tamanho_pe ?? ""}
              onChange={(e) =>
                setFisico({ ...fisico, tamanho_pe: e.target.value === "" ? null : Number(e.target.value) })
              }
              className="h-10 bg-input"
            />
            {fisico.tamanho_pe !== null && !peValido && (
              <span className="text-[11px] normal-case tracking-normal text-state-lost">Tamanho do pé entre 28 e 50</span>
            )}
          </Campo>
        </div>
        <Salvar
          dirty={dirtyFisico}
          disabled={!fisicoValido}
          submitting={submitting === "fisico"}
          label="Salvar características físicas"
          onClick={() => salvar("fisico", {
            tipo_fisico: (fisico.tipo_fisico || null) as PatchModeloInput["tipo_fisico"],
            cor_pele: (fisico.cor_pele || null) as PatchModeloInput["cor_pele"],
            cor_cabelo: (fisico.cor_cabelo || null) as PatchModeloInput["cor_cabelo"],
            altura_cm: fisico.altura_cm,
            tamanho_pe: fisico.tamanho_pe,
            peso_kg: fisico.peso_kg,
            cintura_cm: fisico.cintura_cm,
          }, "Características físicas atualizadas")}
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
                  nome_local: local.nome_local,
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
                  nome_local: null,
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
            nome_local: atendimento.nome_local,
            latitude: atendimento.latitude,
            longitude: atendimento.longitude,
            place_id: atendimento.place_id,
            idiomas: idiomasArray,
            tipo_atendimento_aceito: atendimento.tipo_atendimento_aceito,
          }, "Atendimento atualizado")}
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
        catalogoFetiches={catalogoFetiches}
        fetichesVinculados={fetichesVinculados}
        onVincularFetiche={onVincularFetiche}
        onAtualizarFetiche={onAtualizarFetiche}
        onDesvincularFetiche={onDesvincularFetiche}
        onCriarFetiche={onCriarFetiche}
      />

      <Card title="Repasse e Pix">
        <div className="grid gap-5 sm:grid-cols-2">
          <Campo label="Comissão Elite Baby (%)">
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

      <Card title="Documentos e redes">
        <div className="grid gap-5 sm:grid-cols-2">
          <Campo label="RG">
            <Input
              value={dados.rg}
              placeholder="00.000.000-0"
              onChange={(e) => setDados({ ...dados, rg: formatarRg(e.target.value) })}
              className="h-10 bg-input"
            />
          </Campo>
          <Campo label="CPF">
            <Input
              value={dados.cpf}
              placeholder="000.000.000-00"
              inputMode="numeric"
              onChange={(e) => setDados({ ...dados, cpf: formatarCpf(e.target.value) })}
              className="h-10 bg-input"
            />
            {cpfDigitos !== "" && !cpfCadastroValido && (
              <span className="text-[11px] normal-case tracking-normal text-state-lost">CPF inválido</span>
            )}
          </Campo>
          <div className="sm:col-span-2">
            <Campo label="Endereço residencial">
              <CampoLocalAutocomplete
                valorInicial={dados.endereco_residencial_formatado ?? ""}
                enderecoFormatadoAtual={dados.endereco_residencial_formatado}
                onSelecionar={(local) =>
                  setDados((d) => ({
                    ...d,
                    endereco_residencial_formatado: local.endereco_formatado,
                    place_id_residencial: local.place_id,
                  }))
                }
                onLimpar={() =>
                  setDados((d) => ({
                    ...d,
                    endereco_residencial_formatado: null,
                    place_id_residencial: null,
                  }))
                }
              />
            </Campo>
          </div>
          <Campo label="Instagram">
            <Input
              value={dados.instagram}
              placeholder="@usuario"
              onChange={(e) => setDados({ ...dados, instagram: e.target.value })}
              className="h-10 bg-input"
            />
          </Campo>
          <Campo label="E-mail">
            <Input
              type="email"
              inputMode="email"
              value={dados.email}
              placeholder="contato@exemplo.com"
              onChange={(e) => setDados({ ...dados, email: e.target.value })}
              className="h-10 bg-input"
            />
            {emailTrim !== "" && !emailValido && (
              <span className="text-[11px] normal-case tracking-normal text-state-lost">E-mail inválido</span>
            )}
          </Campo>
        </div>
        <Salvar
          dirty={dirtyDados}
          disabled={!dadosValido}
          submitting={submitting === "dados"}
          label="Salvar documentos e redes"
          onClick={() => salvar("dados", {
            rg: rgNormalizado || null,
            cpf: cpfDigitos || null,
            endereco_residencial_formatado: dados.endereco_residencial_formatado,
            place_id_residencial: dados.place_id_residencial,
            instagram: dados.instagram.trim() || null,
            email: dados.email.trim() || null,
          }, "Documentos e redes atualizados")}
        />
      </Card>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg bg-card p-6 shadow-elev-1 ring-1 ring-border-subtle">
      <h2 className="mb-5 flex items-center gap-2.5 text-base font-semibold text-text-primary">
        <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
        {title}
      </h2>
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
