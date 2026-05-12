"use client"

import { useEffect, useRef, useState } from "react"
import Image from "next/image"

interface ImageLightboxProps {
  src: string
  alt: string
  open: boolean
  onClose: () => void
}

export function ImageLightbox({ src, alt, open, onClose }: ImageLightboxProps) {
  const [zoom, setZoom] = useState(1)
  const [openAnterior, setOpenAnterior] = useState(open)
  const containerRef = useRef<HTMLDivElement>(null)

  if (open !== openAnterior) {
    setOpenAnterior(open)
    if (!open) setZoom(1)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    if (open) document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, onClose])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      setZoom((z) => Math.min(4, Math.max(1, z - e.deltaY * 0.002)))
    }
    el.addEventListener("wheel", onWheel, { passive: false })
    return () => el.removeEventListener("wheel", onWheel)
  }, [open])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={onClose}
    >
      <div
        ref={containerRef}
        className="flex items-center justify-center"
        onClick={(e) => e.stopPropagation()}
        style={{ cursor: zoom > 1 ? "zoom-out" : "zoom-in" }}
      >
        <Image
          src={src}
          alt={alt}
          width={1200}
          height={800}
          unoptimized
          style={{
            transform: `scale(${zoom})`,
            transformOrigin: "center",
            transition: "transform 0.1s ease-out",
            maxHeight: "90vh",
            maxWidth: "90vw",
            width: "auto",
            height: "auto",
            objectFit: "contain",
          }}
        />
      </div>
    </div>
  )
}
