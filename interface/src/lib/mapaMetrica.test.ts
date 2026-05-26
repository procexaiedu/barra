import { describe, expect, it } from "vitest"

import {
  LIMIAR_CALOR_MIN_PONTOS,
  calorHabilitado,
  limitesMetrica,
  normalizarPeso,
  pesoPonto,
  raioBolha,
} from "./mapaMetrica"
import type { MapaClientePonto } from "@/tipos/clientes"

function ponto(over: Partial<MapaClientePonto> = {}): MapaClientePonto {
  return {
    cliente_id: "c1",
    nome: "Cliente",
    latitude: -22.97,
    longitude: -43.18,
    bairro: "Bairro",
    endereco_formatado: "Rua X, 100 — Bairro, Cidade",
    total_atendimentos: 1,
    valor_total: 0,
    estado: "Fechado",
    perfis: [],
    ultima_data: null,
    recorrente: false,
    ...over,
  }
}

describe("calorHabilitado (MAPA-7)", () => {
  it("desabilita abaixo do limiar", () => {
    expect(calorHabilitado(0)).toBe(false)
    expect(calorHabilitado(LIMIAR_CALOR_MIN_PONTOS - 1)).toBe(false)
  })

  it("habilita exatamente no limiar", () => {
    expect(calorHabilitado(LIMIAR_CALOR_MIN_PONTOS)).toBe(true)
  })

  it("habilita acima do limiar", () => {
    expect(calorHabilitado(LIMIAR_CALOR_MIN_PONTOS + 1)).toBe(true)
    expect(calorHabilitado(1000)).toBe(true)
  })
})

describe("limitesMetrica", () => {
  it("retorna min/max do valor_total quando metrica='valor'", () => {
    const pontos = [
      ponto({ valor_total: 100 }),
      ponto({ valor_total: 500 }),
      ponto({ valor_total: 250 }),
    ]
    expect(limitesMetrica(pontos, "valor")).toEqual({ min: 100, max: 500 })
  })

  it("retorna null para metrica='clientes' (caso degenerado)", () => {
    expect(limitesMetrica([ponto()], "clientes")).toBeNull()
  })

  it("retorna null para lista vazia", () => {
    expect(limitesMetrica([], "valor")).toBeNull()
  })
})

describe("pesoPonto", () => {
  it("retorna 1 para metrica='clientes'", () => {
    expect(pesoPonto(ponto({ valor_total: 999 }), "clientes")).toBe(1)
  })

  it("retorna Number(valor_total) para metrica='valor'", () => {
    expect(pesoPonto(ponto({ valor_total: 1234.5 }), "valor")).toBe(1234.5)
  })

  it("retorna total_atendimentos para metrica='atendimentos'", () => {
    expect(pesoPonto(ponto({ total_atendimentos: 7 }), "atendimentos")).toBe(7)
  })
})

describe("normalizarPeso", () => {
  it("colapsa em 0.5 quando min==max (bolhas uniformes)", () => {
    expect(normalizarPeso(50, { min: 50, max: 50 })).toBe(0.5)
  })

  it("colapsa em 0.5 quando não há limites", () => {
    expect(normalizarPeso(50, null)).toBe(0.5)
  })

  it("normaliza linearmente entre min e max", () => {
    expect(normalizarPeso(0, { min: 0, max: 100 })).toBe(0)
    expect(normalizarPeso(50, { min: 0, max: 100 })).toBe(0.5)
    expect(normalizarPeso(100, { min: 0, max: 100 })).toBe(1)
  })

  it("trava em [0..1]", () => {
    expect(normalizarPeso(-10, { min: 0, max: 100 })).toBe(0)
    expect(normalizarPeso(200, { min: 0, max: 100 })).toBe(1)
  })
})

describe("raioBolha (sqrt scaling — área proporcional ao valor)", () => {
  it("retorna o mínimo no extremo inferior", () => {
    expect(raioBolha(0)).toBe(8)
  })

  it("retorna o máximo no extremo superior", () => {
    expect(raioBolha(1)).toBe(28)
  })

  it("é estritamente monotônico ascendente", () => {
    expect(raioBolha(0.25)).toBeLessThan(raioBolha(0.5))
    expect(raioBolha(0.5)).toBeLessThan(raioBolha(0.75))
  })
})
