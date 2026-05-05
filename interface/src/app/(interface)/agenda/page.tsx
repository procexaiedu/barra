"use client"

import { Suspense } from "react"
import { AgendaClient, AgendaSkeleton } from "./AgendaClient"

export default function AgendaPage() {
  return (
    <Suspense fallback={<AgendaSkeleton />}>
      <AgendaClient />
    </Suspense>
  )
}
