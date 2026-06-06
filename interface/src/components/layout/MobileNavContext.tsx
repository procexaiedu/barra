"use client"

import { createContext, useContext, useState, type ReactNode } from "react"

type MobileNavContextValue = {
  drawerAberto: boolean
  abrirDrawer: () => void
  fecharDrawer: () => void
  setDrawerAberto: (aberto: boolean) => void
}

const MobileNavContext = createContext<MobileNavContextValue | null>(null)

export function MobileNavProvider({ children }: { children: ReactNode }) {
  const [drawerAberto, setDrawerAberto] = useState(false)

  return (
    <MobileNavContext.Provider
      value={{
        drawerAberto,
        abrirDrawer: () => setDrawerAberto(true),
        fecharDrawer: () => setDrawerAberto(false),
        setDrawerAberto,
      }}
    >
      {children}
    </MobileNavContext.Provider>
  )
}

export function useMobileNav(): MobileNavContextValue {
  const ctx = useContext(MobileNavContext)
  if (!ctx) {
    throw new Error("useMobileNav deve ser usado dentro de MobileNavProvider")
  }
  return ctx
}
