"use client"

import type { ReactNode } from "react"
import { Sidebar } from "@/components/layout/Sidebar"
import { MobileBlocker } from "@/components/layout/MobileBlocker"

export default function InterfaceLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <MobileBlocker />
      <div className="hidden min-h-screen lg:grid lg:grid-cols-[240px_1fr]">
        <Sidebar />
        <main className="overflow-y-auto p-8">{children}</main>
      </div>
    </>
  )
}
