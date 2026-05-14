"use client"

import { ChevronLeft, ChevronRight } from "lucide-react"
import { DayPicker, type DateRange } from "react-day-picker"
import { ptBR } from "react-day-picker/locale"
import "react-day-picker/style.css"

import { cn } from "@/lib/utils"
import { dataDeIsoYmd, hojeBrtIso, isoYmdDeData } from "@/components/dashboard/utils"

interface Props {
  value: { de: string | null; ate: string | null }
  onChange: (range: { de: string | null; ate: string | null }) => void
  maxIso?: string
  className?: string
}

export function RangeCalendar({ value, onChange, maxIso, className }: Props) {
  const max = maxIso ?? hojeBrtIso()
  const selected: DateRange | undefined =
    value.de
      ? {
          from: dataDeIsoYmd(value.de),
          to: value.ate ? dataDeIsoYmd(value.ate) : undefined,
        }
      : undefined

  return (
    <DayPicker
      data-slot="range-calendar"
      mode="range"
      locale={ptBR}
      weekStartsOn={0}
      selected={selected}
      onSelect={(range) => {
        if (!range) {
          onChange({ de: null, ate: null })
          return
        }
        onChange({
          de: range.from ? isoYmdDeData(range.from) : null,
          ate: range.to ? isoYmdDeData(range.to) : null,
        })
      }}
      disabled={{ after: dataDeIsoYmd(max) }}
      showOutsideDays
      components={{
        Chevron: (chevronProps) => {
          if (chevronProps.orientation === "right") {
            return <ChevronRight className="size-4" />
          }
          return <ChevronLeft className="size-4" />
        },
      }}
      className={cn("rdp-barra text-sm text-text-primary", className)}
      classNames={{
        months: "flex flex-col gap-3",
        month: "flex flex-col gap-3",
        month_caption: "flex h-9 items-center justify-center px-9 text-sm font-semibold capitalize text-text-primary",
        nav: "absolute inset-x-0 top-0 flex h-9 items-center justify-between px-1",
        button_previous:
          "inline-flex size-7 items-center justify-center rounded-md text-text-secondary hover:bg-accent hover:text-text-primary disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        button_next:
          "inline-flex size-7 items-center justify-center rounded-md text-text-secondary hover:bg-accent hover:text-text-primary disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        month_grid: "w-full border-collapse",
        weekdays: "flex",
        weekday: "flex-1 text-center text-[11px] font-semibold uppercase tracking-[0.06em] text-text-muted",
        week: "mt-1 flex",
        day: "flex-1 p-0 text-center",
        day_button:
          "inline-flex size-9 items-center justify-center rounded-md text-sm text-text-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:text-text-muted disabled:opacity-50",
        today: "font-semibold text-text-brand",
        outside: "text-text-muted opacity-50",
        disabled: "text-text-muted opacity-40",
        selected: "",
        range_start:
          "[&>button]:bg-primary [&>button]:text-primary-foreground [&>button]:hover:bg-primary rounded-l-md bg-accent",
        range_end:
          "[&>button]:bg-primary [&>button]:text-primary-foreground [&>button]:hover:bg-primary rounded-r-md bg-accent",
        range_middle:
          "[&>button]:bg-transparent [&>button]:text-text-primary [&>button]:hover:bg-accent/60 bg-accent",
        root: "relative inline-block",
      }}
    />
  )
}
