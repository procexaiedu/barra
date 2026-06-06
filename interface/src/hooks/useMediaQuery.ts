import { useSyncExternalStore } from "react"

// Hook de media query SSR-safe. No servidor (e no primeiro render do client)
// retorna `false`, evitando hydration mismatch; o valor real chega após o mount
// via useSyncExternalStore. Use só quando a ÁRVORE precisa divergir
// estruturalmente — para reflow puramente visual, prefira classes Tailwind.
export function useMediaQuery(query: string): boolean {
  const subscribe = (onChange: () => void) => {
    if (typeof window === "undefined" || !window.matchMedia) return () => {}
    const mql = window.matchMedia(query)
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }

  const getSnapshot = () => {
    if (typeof window === "undefined" || !window.matchMedia) return false
    return window.matchMedia(query).matches
  }

  const getServerSnapshot = () => false

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}

// Corte mobile alinhado ao breakpoint `lg` do Tailwind (1024px), o mesmo ponto
// onde a sidebar dá lugar à bottom nav.
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 1023px)")
}
