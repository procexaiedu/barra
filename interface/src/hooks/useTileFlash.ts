"use client"

import { useEffect, useRef, useState } from "react"

export function useTileFlash(value: number): boolean {
  const prevRef = useRef<number>(value)
  const [flashing, setFlashing] = useState(false)

  useEffect(() => {
    if (prevRef.current !== value) {
      prevRef.current = value
      setFlashing(true)
      const t = setTimeout(() => setFlashing(false), 700)
      return () => clearTimeout(t)
    }
  }, [value])

  return flashing
}
