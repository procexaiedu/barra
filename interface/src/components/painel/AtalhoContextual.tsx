"use client"

import Link from "next/link"
import { Receipt, MessagesSquare, QrCode, CalendarPlus } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { MetricasDia, ModeloAtiva } from "@/tipos/painel"

interface Atalho {
  key: string
  visible: boolean
  text: string
  icon: typeof Receipt
  variant: "default" | "secondary"
  href: string
}

export function AtalhoContextual({
  metricas,
  modeloAtiva,
}: {
  metricas: MetricasDia
  modeloAtiva: ModeloAtiva | null
}) {
  const atalhos: Atalho[] = [
    {
      key: "conectar",
      visible: modeloAtiva !== null && modeloAtiva.evolution_instance_id === null,
      text: "Conectar WhatsApp da modelo",
      icon: QrCode,
      variant: "default",
      href: modeloAtiva ? `/modelos?modelo=${modeloAtiva.id}&aba=perfil` : "#",
    },
    {
      key: "pix",
      visible: metricas.pix_em_revisao_pendentes > 0,
      text: `Ver ${metricas.pix_em_revisao_pendentes} Pix em revisão`,
      icon: Receipt,
      variant: "secondary",
      href: "/pix?status=em_revisao",
    },
    {
      key: "atendimentos",
      visible: metricas.abertos > 0,
      text: `Ver ${metricas.abertos} atendimentos abertos`,
      icon: MessagesSquare,
      variant: "secondary",
      href: "/atendimentos",
    },
    {
      key: "bloquear",
      visible: true,
      text: "Bloquear horário",
      icon: CalendarPlus,
      variant: "secondary",
      href: "/agenda?action=bloquear",
    },
  ]

  const visibleAtalhos = atalhos.filter((a) => a.visible)

  return (
    <section aria-label="Atalhos" className="px-8 py-6">
      <div className="mb-6 border-t border-border" />
      <div className="flex flex-wrap gap-3">
        {visibleAtalhos.map((atalho) => {
          const Icon = atalho.icon
          return (
            <Button
              key={atalho.key}
              variant={atalho.variant === "default" ? "default" : "secondary"}
              nativeButton={false}
              render={<Link href={atalho.href} />}
            >
              <Icon size={16} strokeWidth={1.5} />
              {atalho.text}
            </Button>
          )
        })}
      </div>
    </section>
  )
}
