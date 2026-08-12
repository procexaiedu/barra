import { describe, expect, it } from "vitest"
import {
  corpoAtualizarPreco,
  estadoDoPiso,
  lerPrecoMinimo,
  minimoAlterado,
  pisoDoErro422,
} from "./precoMinimo"

describe("estadoDoPiso", () => {
  it("sem piso cadastrado = só o percentual global manda", () => {
    expect(estadoDoPiso(400, null)).toEqual({ tipo: "sem_piso" })
  })

  it("piso abaixo do preço = a linha desce até ali", () => {
    expect(estadoDoPiso(400, 300)).toEqual({ tipo: "piso", valor: 300 })
  })

  it("piso igual ao preço = linha não descontável (Pernoite, 30min da Catarina)", () => {
    expect(estadoDoPiso(2000, 2000)).toEqual({ tipo: "nao_descontavel", valor: 2000 })
    expect(estadoDoPiso(250, 250.001)).toEqual({ tipo: "nao_descontavel", valor: 250.001 })
  })

  it("campo ausente na resposta é desconhecido, nunca 'sem piso'", () => {
    expect(estadoDoPiso(400, undefined)).toEqual({ tipo: "desconhecido" })
  })
})

describe("lerPrecoMinimo", () => {
  it("vazio = sem piso", () => {
    expect(lerPrecoMinimo("", 400)).toEqual({ minimo: null })
    expect(lerPrecoMinimo("   ", 400)).toEqual({ minimo: null })
  })

  it("aceita vírgula decimal e piso igual ao preço", () => {
    expect(lerPrecoMinimo("300,50", 400)).toEqual({ minimo: 300.5 })
    expect(lerPrecoMinimo("400", 400)).toEqual({ minimo: 400 })
  })

  it("recusa piso acima do preço (o CHECK do banco, antes da ida ao servidor)", () => {
    const lido = lerPrecoMinimo("500", 400)
    expect("erro" in lido).toBe(true)
    expect("erro" in lido && lido.erro).toMatch(/não pode ser maior que o preço/)
  })

  it("recusa entrada não numérica e negativa", () => {
    expect("erro" in lerPrecoMinimo("abc", 400)).toBe(true)
    expect("erro" in lerPrecoMinimo("-1", 400)).toBe(true)
  })
})

describe("minimoAlterado", () => {
  it("campo intocado não conta como alteração", () => {
    expect(minimoAlterado(null, null)).toBe(false)
    expect(minimoAlterado(null, undefined)).toBe(false)
    expect(minimoAlterado(300, 300)).toBe(false)
  })

  it("limpar, criar ou mudar o piso conta", () => {
    expect(minimoAlterado(null, 300)).toBe(true)
    expect(minimoAlterado(300, null)).toBe(true)
    expect(minimoAlterado(250, 300)).toBe(true)
  })
})

describe("corpoAtualizarPreco", () => {
  it("reajuste de preço sem tocar no piso OMITE preco_minimo (preserva o piso)", () => {
    const corpo = corpoAtualizarPreco({ preco: 450, minimo: 300, minimoOriginal: 300 })
    expect(corpo).toEqual({ preco: 450 })
    expect("preco_minimo" in corpo).toBe(false)
  })

  it("piso desconhecido pelo painel nunca é enviado por acidente", () => {
    const corpo = corpoAtualizarPreco({ preco: 450, minimo: null, minimoOriginal: undefined })
    expect("preco_minimo" in corpo).toBe(false)
  })

  it("esvaziar o campo manda null explícito (limpa o piso)", () => {
    expect(corpoAtualizarPreco({ preco: 450, minimo: null, minimoOriginal: 300 })).toEqual({
      preco: 450,
      preco_minimo: null,
    })
  })

  it("piso novo vai junto do preço", () => {
    expect(corpoAtualizarPreco({ preco: 450, minimo: 350, minimoOriginal: 300 })).toEqual({
      preco: 450,
      preco_minimo: 350,
    })
  })
})

describe("pisoDoErro422", () => {
  it("extrai o piso da mensagem que o backend devolve", () => {
    expect(
      pisoDoErro422(
        "preco abaixo do preco_minimo cadastrado (300.00): envie preco_minimo junto para ajustar os dois.",
      ),
    ).toBe(300)
  })

  it("devolve null para qualquer outro 422", () => {
    expect(pisoDoErro422("Entrada invalida.")).toBeNull()
  })
})
