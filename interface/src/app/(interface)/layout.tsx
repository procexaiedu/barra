"use client"

import type { ReactNode } from "react"
import { Sidebar } from "@/components/layout/Sidebar"
import { BottomNav } from "@/components/layout/BottomNav"
import { MobileDrawer } from "@/components/layout/MobileDrawer"
import { MobileNavProvider } from "@/components/layout/MobileNavContext"

export default function InterfaceLayout({ children }: { children: ReactNode }) {
  return (
    <MobileNavProvider>
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1320px] px-4 py-5 pb-[calc(4rem+env(safe-area-inset-bottom))] lg:px-8 lg:py-8 lg:pb-8">
            {children}
          </div>
        </main>
      </div>
      <BottomNav />
      <MobileDrawer />
    </MobileNavProvider>
  )
}
