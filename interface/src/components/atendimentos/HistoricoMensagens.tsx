"use client"

import { useMemo, useState } from "react"
import Image from "next/image"
import { FileText, MessageSquareOff } from "lucide-react"
import { Button } from "@/components/ui/button"
import { formatHorario } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { MensagemAtendimento } from "@/tipos/atendimentos"
import { ImageLightbox } from "@/components/ui/image-lightbox"

const direcaoLabel: Record<MensagemAtendimento["direcao"], string> = {
  cliente: "Cliente",
  ia: "IA",
  modelo_manual: "MODELO",
}

export function HistoricoMensagens({ mensagens }: { mensagens: MensagemAtendimento[] }) {
  const [midiaAberta, setMidiaAberta] = useState<MensagemAtendimento | null>(null)

  const ordenadas = useMemo(
    () => [...mensagens].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()),
    [mensagens]
  )

  if (ordenadas.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2.5 py-6 text-center">
        <div className="flex size-10 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
          <MessageSquareOff size={18} strokeWidth={1.75} className="text-text-muted" />
        </div>
        <div>
          <p className="text-[13px] text-text-secondary">Nenhuma mensagem vinculada a este atendimento.</p>
          <p className="mt-0.5 text-[12px] text-text-muted">O histórico aparece conforme as mensagens chegam.</p>
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="space-y-3">
        {ordenadas.map((mensagem) => (
          <MensagemLinha
            key={mensagem.id}
            mensagem={mensagem}
            onAbrirImagem={setMidiaAberta}
          />
        ))}
      </div>

      <ImageLightbox
        open={!!midiaAberta && !!midiaAberta.media_url}
        src={midiaAberta?.media_url ?? ""}
        alt={midiaAberta?.media_object_key?.split("/").pop() ?? "Imagem"}
        onClose={() => setMidiaAberta(null)}
      />
    </>
  )
}

function MensagemLinha({
  mensagem,
  onAbrirImagem,
}: {
  mensagem: MensagemAtendimento
  onAbrirImagem: (m: MensagemAtendimento) => void
}) {
  const [expandida, setExpandida] = useState(false)
  const longa = (mensagem.conteudo?.length ?? 0) > 140
  const isModelo = mensagem.direcao === "ia" || mensagem.direcao === "modelo_manual"
  const hasMedia = mensagem.tipo !== "texto" || mensagem.media_object_key

  return (
    <article className={cn("flex", isModelo ? "justify-end" : "justify-start")}>
      <div className="max-w-[76%]">
        <div className={cn("mb-1 flex items-center gap-2 text-xs", isModelo ? "justify-end" : "justify-start")}>
          <span className={mensagem.direcao === "ia" ? "font-semibold text-text-brand" : "font-medium text-text-muted"}>
            {direcaoLabel[mensagem.direcao]}
          </span>
          <span className="text-text-muted">{formatHorario(mensagem.created_at)}</span>
        </div>
        <div
          className={cn(
            "rounded-lg px-4 py-3 text-sm text-text-primary",
            mensagem.direcao === "ia" ? "bg-muted ring-1 ring-border-brand/30" : "",
            mensagem.direcao === "modelo_manual" ? "bg-muted" : "",
            mensagem.direcao === "cliente" ? "bg-card border border-border" : ""
          )}
        >
          {hasMedia && (
            mensagem.tipo === "imagem" && mensagem.media_url ? (
              <button
                type="button"
                onClick={() => onAbrirImagem(mensagem)}
                className="mb-2 block overflow-hidden rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Image
                  src={mensagem.media_url}
                  alt={mensagem.media_object_key?.split("/").pop() ?? "imagem"}
                  width={240}
                  height={180}
                  unoptimized
                  className="max-w-[240px] rounded-md object-cover transition-opacity hover:opacity-90"
                />
              </button>
            ) : mensagem.tipo === "audio" && mensagem.media_url ? (
              <audio controls src={mensagem.media_url} className="mb-2 w-full max-w-[260px]" />
            ) : (
              <div className="mb-2 inline-flex items-center gap-2 rounded-md bg-accent px-2 py-1 font-mono text-xs text-text-muted">
                <FileText size={14} strokeWidth={1.5} />
                {mensagem.media_object_key?.split("/").pop() ?? mensagem.tipo}
              </div>
            )
          )}
          {mensagem.conteudo && (
            <>
              <p className={cn("whitespace-pre-wrap", !expandida && "line-clamp-2")}>
                {mensagem.conteudo}
              </p>
              {longa && (
                <Button
                  variant="ghost"
                  size="xs"
                  className="mt-2 h-6 px-2"
                  onClick={() => setExpandida((value) => !value)}
                >
                  {expandida ? "Recolher" : "Expandir"}
                </Button>
              )}
            </>
          )}
        </div>
      </div>
    </article>
  )
}
