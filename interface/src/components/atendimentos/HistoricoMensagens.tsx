"use client"

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import Image from "next/image"
import { FileText, MessageSquareOff } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { formatHorario } from "@/lib/formatters"
import { PAGINA_MENSAGENS } from "@/hooks/useAtendimentos"
import { cn } from "@/lib/utils"
import type { MensagemAtendimento, MensagensPaginaResponse } from "@/tipos/atendimentos"
import { ImageLightbox } from "@/components/ui/image-lightbox"

const direcaoLabel: Record<MensagemAtendimento["direcao"], string> = {
  cliente: "Cliente",
  ia: "IA",
  modelo_manual: "MODELO",
}

/** Cursor do backend: "created_at|id". `created_at` sozinho empata quando o worker
 *  grava a rajada do turno no mesmo instante. */
function cursorDe(mensagem: MensagemAtendimento): string {
  return `${mensagem.created_at}|${mensagem.id}`
}

/** Cronológica, com o id (uuidv7, monotônico) desempatando o mesmo timestamp. */
function ordenar(mensagens: MensagemAtendimento[]): MensagemAtendimento[] {
  return [...mensagens].sort((a, b) => {
    const delta = new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    return delta !== 0 ? delta : a.id.localeCompare(b.id)
  })
}

/** O contêiner de rolagem é um ancestral (o painel de detalhe / o modal), não este
 *  componente — para preservar a posição ao prepender é preciso achá-lo. */
function acharScroller(inicio: HTMLElement | null): HTMLElement | null {
  let node = inicio?.parentElement ?? null
  while (node) {
    const overflow = getComputedStyle(node).overflowY
    if ((overflow === "auto" || overflow === "scroll") && node.scrollHeight > node.clientHeight) {
      return node
    }
    node = node.parentElement
  }
  return null
}

export function HistoricoMensagens({ mensagens }: { mensagens: MensagemAtendimento[] }) {
  // O atendimento vem da própria mensagem: os dois chamadores renderizam este
  // componente sem passar o id, e a paginação precisa dele para buscar o resto.
  const atendimentoId = mensagens[0]?.atendimento_id ?? null

  if (mensagens.length === 0 || !atendimentoId) {
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

  // key = trocar de atendimento zera páginas carregadas, cursor e âncora de scroll.
  return <Historico key={atendimentoId} atendimentoId={atendimentoId} mensagens={mensagens} />
}

function Historico({
  atendimentoId,
  mensagens,
}: {
  atendimentoId: string
  mensagens: MensagemAtendimento[]
}) {
  const [midiaAberta, setMidiaAberta] = useState<MensagemAtendimento | null>(null)
  const [antigas, setAntigas] = useState<MensagemAtendimento[]>([])
  const [temMais, setTemMais] = useState(false)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState(false)
  const cursorRef = useRef<string | null>(null)
  const raizRef = useRef<HTMLDivElement>(null)
  const ancoraRef = useRef<{ scroller: HTMLElement; altura: number; topo: number } | null>(null)

  const ordenadas = useMemo(() => ordenar([...antigas, ...mensagens]), [antigas, mensagens])
  const cursorTopo = useMemo(() => {
    const maisAntiga = ordenar(mensagens)[0]
    return maisAntiga ? cursorDe(maisAntiga) : null
  }, [mensagens])

  const jaPaginou = antigas.length > 0

  useEffect(() => {
    // Depois da primeira página quem manda é o next_cursor do backend.
    if (jaPaginou || !cursorTopo) return
    // Abaixo do menor recorte que os chamadores pedem, o que chegou já é a conversa
    // inteira — não vale um round-trip só para descobrir isso (`temMais` já é false).
    if (mensagens.length < PAGINA_MENSAGENS) return
    let cancelado = false
    // Sonda de 1 linha: responde "existe alguma mensagem anterior?" sem trazer página.
    api<MensagensPaginaResponse>(
      `/v1/atendimentos/${atendimentoId}/mensagens?limit=1&cursor=${encodeURIComponent(cursorTopo)}`
    )
      .then((res) => {
        if (!cancelado) setTemMais((res.items?.length ?? 0) > 0)
      })
      .catch(() => {
        // Sem sonda o botão fica escondido; o que está na tela continua íntegro.
      })
    return () => {
      cancelado = true
    }
  }, [atendimentoId, cursorTopo, jaPaginou, mensagens.length])

  useLayoutEffect(() => {
    const ancora = ancoraRef.current
    if (!ancora) return
    ancoraRef.current = null
    // As antigas entraram acima: compensa o crescimento para a leitura não saltar.
    ancora.scroller.scrollTop = ancora.scroller.scrollHeight - ancora.altura + ancora.topo
  }, [antigas])

  const carregarMais = useCallback(async () => {
    if (carregando) return
    const cursor = cursorRef.current ?? cursorTopo
    if (!cursor) return
    setCarregando(true)
    setErro(false)
    const scroller = acharScroller(raizRef.current)
    const antes = scroller
      ? { scroller, altura: scroller.scrollHeight, topo: scroller.scrollTop }
      : null
    try {
      const res = await api<MensagensPaginaResponse>(
        `/v1/atendimentos/${atendimentoId}/mensagens?limit=${PAGINA_MENSAGENS}&cursor=${encodeURIComponent(cursor)}`
      )
      const recebidas = Array.isArray(res.items) ? res.items : []
      ancoraRef.current = antes
      setAntigas((prev) => {
        const vistos = new Set(prev.map((m) => m.id))
        return [...recebidas.filter((m) => !vistos.has(m.id)), ...prev]
      })
      cursorRef.current = res.next_cursor ?? null
      setTemMais(!!res.next_cursor)
    } catch {
      setErro(true)
    } finally {
      setCarregando(false)
    }
  }, [atendimentoId, carregando, cursorTopo])

  return (
    <>
      <div ref={raizRef} className="space-y-3">
        {temMais && (
          <div className="flex flex-col items-center gap-1.5 rounded-md bg-muted px-2.5 py-2 ring-1 ring-border-subtle">
            <p className="text-[12px] text-text-secondary">
              Mostrando as mensagens mais recentes. O começo da conversa ainda não foi carregado.
            </p>
            <Button variant="ghost" size="xs" className="h-7 px-2" disabled={carregando} onClick={carregarMais}>
              {carregando ? "Carregando…" : "Carregar mensagens anteriores"}
            </Button>
          </div>
        )}
        {!temMais && jaPaginou && (
          <p className="rounded-md bg-muted px-2.5 py-1.5 text-center text-[12px] text-text-muted ring-1 ring-border-subtle">
            Começo da conversa.
          </p>
        )}
        {erro && (
          <p className="text-center text-[12px] text-destructive">
            Não deu para carregar as mensagens anteriores. Tente de novo.
          </p>
        )}
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
