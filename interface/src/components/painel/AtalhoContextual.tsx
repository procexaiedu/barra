"use client"

import Link from "next/link"
import { Receipt, MessagesSquare, QrCode, CalendarPlus } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { MetricasDia, ModeloAtiva } from "@/tipos/painel"

type Atalho =
  | {
      key: string
      visible: boolean
      text: string
      icon: typeof Receipt
      variant: "default" | "secondary"
      kind: "link"
      href: string
    }
  | {
      key: string
      visible: boolean
      text: string
      icon: typeof Receipt
      variant: "default" | "secondary"
      kind: "action"
      onClick: () => void
    }

export function AtalhoContextual({
  metricas,
  modeloAtiva,
  onBloquear,
}: {
  metricas: MetricasDia
  modeloAtiva: ModeloAtiva | null
  onBloquear?: () => void
}) {
  const atalhos: Atalho[] = [
    {
      key: "conectar",
      visible: modeloAtiva !== null && modeloAtiva.evolution_status !== "conectado",
      text: "Conectar WhatsApp da modelo",
      icon: QrCode,
      variant: "default",
      kind: "link",
      href: modeloAtiva ? `/modelos?modelo=${modeloAtiva.id}&aba=perfil` : "#",
    },
    {
      key: "pix",
      visible: metricas.pix_em_revisao_pendentes > 0,
      text: `Ver ${metricas.pix_em_revisao_pendentes} Pix em revisão`,
      icon: Receipt,
      variant: "secondary",
      kind: "link",
      href: "/pix?status=em_revisao",
    },
    {
      key: "atendimentos",
      visible: metricas.abertos > 0,
      text: `Ver ${metricas.abertos} atendimentos abertos`,
      icon: MessagesSquare,
      variant: "secondary",
      kind: "link",
      href: "/atendimentos",
    },
    {
      key: "bloquear",
      visible: Boolean(onBloquear),
      text: "Bloquear horário",
      icon: CalendarPlus,
      variant: "secondary",
      kind: "action",
      onClick: onBloquear ?? (() => {}),
    },
  ]

  const visibleAtalhos = atalhos.filter((a) => a.visible)

  return (
    <section aria-label="Atalhos" className="px-8 py-6">
      <div className="rule-aurum mb-6" />
      <div className="flex flex-wrap gap-3">
        {visibleAtalhos.map((atalho) => {
          const Icon = atalho.icon
          const variant = atalho.variant === "default" ? "default" : "secondary"
          if (atalho.kind === "link") {
            return (
              <Button
                key={atalho.key}
                variant={variant}
                nativeButton={false}
                render={<Link href={atalho.href} />}
              >
                <Icon size={16} strokeWidth={1.5} />
                {atalho.text}
              </Button>
            )
          }
          return (
            <Button key={atalho.key} variant={variant} onClick={atalho.onClick}>
              <Icon size={16} strokeWidth={1.5} />
              {atalho.text}
            </Button>
          )
        })}
      </div>
    </section>
  )
}
