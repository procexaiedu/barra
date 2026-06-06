"use client"

import type { ReactNode } from "react"
import { Sidebar } from "@/components/layout/Sidebar"
import { MobileBlocker } from "@/components/layout/MobileBlocker"

export default function InterfaceLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <MobileBlocker />
      <div className="hidden min-h-screen lg:flex">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1320px] px-4 py-6 2xl:px-8 2xl:py-8">{children}</div>
        </main>
      </div>
    </>
  )
}
