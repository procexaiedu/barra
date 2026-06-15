"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Loader2, Plus, Upload, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogBody, DialogCloseButton, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type { TipoMidia, UploadUrlResponse } from "@/tipos/modelos"

const TAGS_PREDEFINIDAS = ["Rosto", "Corpo", "Lingerie", "Sensual", "Vídeo"]

export function DialogMidiaUpload({
  open,
  modo,
  tagsExistentes = [],
  onOpenChange,
  onCriarUploadUrl,
  onConfirmarMidia,
  onConfirmarPerfil,
}: {
  open: boolean
  modo: "midia" | "perfil"
  tagsExistentes?: string[]
  onOpenChange: (open: boolean) => void
  onCriarUploadUrl: (filename: string, contentType: string, perfil: boolean) => Promise<UploadUrlResponse | null>
  onConfirmarMidia: (input: { tipo: TipoMidia; tag: string; object_key: string; aprovada: boolean }) => Promise<void>
  onConfirmarPerfil: (objectKey: string) => Promise<void>
}) {
  const [file, setFile] = useState<File | null>(null)
  const [tag, setTag] = useState("")
  const [aprovada, setAprovada] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [tentou, setTentou] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const tipo = useMemo<TipoMidia>(() => file?.type.startsWith("video/") ? "video" : "foto", [file])
  const limite = modo === "perfil" ? 5 * 1024 * 1024 : 50 * 1024 * 1024
  const mimeOk = modo === "perfil"
    ? ["image/jpeg", "image/png", "image/webp"].includes(file?.type ?? "")
    : Boolean(file?.type.startsWith("image/") || file?.type.startsWith("video/"))

  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])

  const erro = !file
    ? "Selecione uma imagem ou vídeo."
    : !mimeOk
      ? (modo === "perfil" ? "Use JPEG, PNG ou WebP." : "Envie uma imagem ou vídeo.")
      : (file.size > limite)
        ? `Arquivo acima de ${modo === "perfil" ? "5" : "50"} MB.`
        : tag.length > 50
          ? "Tag muito longa (máx. 50)."
          : null
  const valido = erro === null

  const escolherArquivo = () => inputRef.current?.click()
  const removerArquivo = () => {
    setFile(null)
    if (inputRef.current) inputRef.current.value = ""
  }

  const submit = async () => {
    setTentou(true)
    if (!file || !valido) return
    setSubmitting(true)
    try {
      const upload = await onCriarUploadUrl(file.name, file.type, modo === "perfil")
      if (!upload) return
      const putRes = await fetch(upload.upload_url, {
        method: "PUT",
        headers: { "content-type": file.type },
        body: file,
      })
      if (!putRes.ok) {
        throw new Error(`Falha no upload ao MinIO (HTTP ${putRes.status}).`)
      }
      if (modo === "perfil") {
        await onConfirmarPerfil(upload.object_key)
        toast.success("Foto de perfil atualizada")
      } else {
        await onConfirmarMidia({ tipo, tag: tag.trim(), object_key: upload.object_key, aprovada })
        toast.success("Midia adicionada")
      }
      removerArquivo()
      setTag("")
      setAprovada(true)
      setTentou(false)
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro no envio")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !submitting && onOpenChange(value)}>
      <DialogContent size="sm">
        <DialogHeader className="items-start justify-between gap-4">
          <div>
            <DialogTitle className="text-lg font-semibold">{modo === "perfil" ? "Alterar foto de perfil" : "Adicionar midia"}</DialogTitle>
            <DialogDescription>{modo === "perfil" ? "Imagem JPEG, PNG ou WebP ate 5 MB." : "Imagem ou video ate 50 MB."}</DialogDescription>
          </div>
          <DialogCloseButton />
        </DialogHeader>
        <DialogBody>
          <input
            ref={inputRef}
            type="file"
            accept={modo === "perfil" ? "image/jpeg,image/png,image/webp" : "image/*,video/*"}
            className="sr-only"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          {file && previewUrl ? (
            <div className="overflow-hidden rounded-lg border border-border bg-ink-0">
              <button
                type="button"
                onClick={escolherArquivo}
                aria-label="Trocar arquivo"
                className="group relative block max-h-64 w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
              >
                {tipo === "foto" ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={previewUrl} alt={file.name} className="max-h-64 w-full bg-black object-contain" />
                ) : (
                  <video src={previewUrl} muted playsInline preload="metadata" className="max-h-64 w-full bg-black object-contain" />
                )}
                <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-ink-0/0 text-sm font-medium text-white opacity-0 transition group-hover:bg-ink-0/45 group-hover:opacity-100">
                  Trocar arquivo
                </span>
              </button>
              <div className="flex items-center gap-2 border-t border-border px-3 py-2 text-xs text-text-secondary">
                <span className="truncate font-medium">{file.name}</span>
                <span className="ml-auto shrink-0 text-text-muted">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
                <button
                  type="button"
                  onClick={removerArquivo}
                  aria-label="Remover arquivo"
                  className="shrink-0 rounded p-0.5 text-text-muted transition-colors hover:text-state-lost focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <X size={14} strokeWidth={1.75} />
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={escolherArquivo}
              className="flex min-h-44 w-full flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted p-6 text-center text-sm text-text-muted transition-colors hover:border-border-strong hover:text-text-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <Upload className="mb-2" size={24} strokeWidth={1.5} />
              Clique para selecionar do computador
            </button>
          )}
          {modo === "midia" && (
            <div className="mt-4 space-y-4">
              <div className="grid gap-2">
                <span className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
                  Tag <span className="font-normal normal-case tracking-normal text-text-muted/70">(opcional)</span>
                </span>
                <CampoTag value={tag} onChange={setTag} sugestoes={tagsExistentes} />
              </div>
              <label className="inline-flex items-center gap-2 text-sm text-text-secondary">
                <input type="checkbox" checked={aprovada} onChange={(event) => setAprovada(event.target.checked)} className="size-4 accent-primary" />
                Disponível no atendimento
              </label>
            </div>
          )}
          {tentou && erro && <p className="mt-4 text-sm text-state-lost">{erro}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>Cancelar</Button>
          <Button variant="primary" onClick={submit} disabled={!valido || submitting}>
            {submitting && <Loader2 className="animate-spin" />}
            Enviar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Combobox de tag única: digita livremente para criar uma tag nova, ou escolhe
// uma das sugestões (pré-definidas + tags já usadas pela modelo) com busca.
function CampoTag({
  value,
  onChange,
  sugestoes,
}: {
  value: string
  onChange: (value: string) => void
  sugestoes: string[]
}) {
  const [aberto, setAberto] = useState(false)

  const todas = useMemo(() => {
    const porChave = new Map<string, string>()
    for (const t of [...TAGS_PREDEFINIDAS, ...sugestoes]) {
      const limpo = t.trim()
      const chave = limpo.toLowerCase()
      if (chave && !porChave.has(chave)) porChave.set(chave, limpo)
    }
    return [...porChave.values()]
  }, [sugestoes])

  const q = value.trim().toLowerCase()
  const filtradas = useMemo(() => todas.filter((t) => t.toLowerCase().includes(q)), [todas, q])
  const temExato = todas.some((t) => t.toLowerCase() === q)
  const mostrarCriar = q.length > 0 && !temExato

  const selecionar = (t: string) => {
    onChange(t)
    setAberto(false)
  }

  return (
    <div className="relative">
      <Input
        value={value}
        maxLength={50}
        placeholder="Buscar ou criar uma tag"
        onChange={(event) => { onChange(event.target.value); setAberto(true) }}
        onFocus={() => setAberto(true)}
        onBlur={() => setAberto(false)}
        className="h-10 border-border bg-input"
      />
      {aberto && (filtradas.length > 0 || mostrarCriar) && (
        <ul
          role="listbox"
          className="absolute z-20 mt-1 max-h-48 w-full overflow-auto rounded-lg border border-border bg-card p-1 shadow-lg"
        >
          {filtradas.map((t) => (
            <li key={t}>
              <button
                type="button"
                role="option"
                aria-selected={t.toLowerCase() === q}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => selecionar(t)}
                className={cn(
                  "flex w-full items-center rounded px-2.5 py-1.5 text-left text-sm text-text-secondary transition-colors hover:bg-muted",
                  t.toLowerCase() === q && "text-text-primary",
                )}
              >
                {t}
              </button>
            </li>
          ))}
          {mostrarCriar && (
            <li>
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => selecionar(value.trim())}
                className="flex w-full items-center gap-1.5 rounded px-2.5 py-1.5 text-left text-sm text-text-primary transition-colors hover:bg-muted"
              >
                <Plus size={14} strokeWidth={1.75} className="shrink-0 text-text-muted" />
                Criar “{value.trim()}”
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
