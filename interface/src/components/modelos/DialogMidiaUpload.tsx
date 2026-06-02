"use client"

import { useMemo, useState } from "react"
import { Loader2, Upload } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogBody, DialogCloseButton, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import type { TipoMidia, UploadUrlResponse } from "@/tipos/modelos"

export function DialogMidiaUpload({
  open,
  modo,
  onOpenChange,
  onCriarUploadUrl,
  onConfirmarMidia,
  onConfirmarPerfil,
}: {
  open: boolean
  modo: "midia" | "perfil"
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
  const tipo = useMemo<TipoMidia>(() => file?.type.startsWith("video/") ? "video" : "foto", [file])
  const limite = modo === "perfil" ? 5 * 1024 * 1024 : 50 * 1024 * 1024
  const mimeOk = modo === "perfil"
    ? ["image/jpeg", "image/png", "image/webp"].includes(file?.type ?? "")
    : Boolean(file?.type.startsWith("image/") || file?.type.startsWith("video/"))
  const valido = Boolean(file) && mimeOk && (file?.size ?? 0) <= limite && (modo === "perfil" || tag.trim().length > 0 && tag.length <= 50)

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
      setFile(null)
      setTag("")
      setAprovada(true)
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
        <label className="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted p-6 text-center text-sm text-text-muted focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2">
          <Upload className="mb-2" size={24} strokeWidth={1.5} />
          {file ? file.name : "Selecionar arquivo"}
          <input
            type="file"
            accept={modo === "perfil" ? "image/jpeg,image/png,image/webp" : "image/*,video/*"}
            className="sr-only"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        {modo === "midia" && (
          <div className="mt-4 space-y-4">
            <label className="grid gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
              Tag
              <Input value={tag} maxLength={60} onChange={(event) => setTag(event.target.value)} className="h-10 bg-input" />
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-text-secondary">
              <input type="checkbox" checked={aprovada} onChange={(event) => setAprovada(event.target.checked)} className="size-4 accent-primary" />
              Disponível no atendimento
            </label>
          </div>
        )}
        {tentou && !valido && <p className="mt-4 text-sm text-state-lost">Arquivo, tamanho ou tag inválidos.</p>}
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
