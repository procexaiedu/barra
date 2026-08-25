import { describe, expect, it } from "vitest"
import type { MotivoDeSuspeita } from "@/tipos/pix"
import {
  lerSuspeita,
  motivoRejeicaoOptions,
  motivoSuspeitaFiltroOptions,
  rejeicaoSugerida,
  rotuloDaSuspeita,
} from "./utils"

/**
 * Ticket 07 — o painel passa a falar o MESMO vocabulário de suspeita do backend.
 *
 * O bug que estes testes fecham: `motivo_em_revisao` sempre veio do backend como prosa livre
 * ("valor extraido 80.00 < esperado R$100"), mas o painel tipava a coluna como um conjunto
 * fechado de slugs que ninguém emitia — `motivoRevisaoLabel[prosa]` era `undefined` e a linha do
 * motivo na lista de Pix renderizava um parágrafo VAZIO em todo item em revisão.
 */

const TODOS: MotivoDeSuspeita[] = [
  "imagem_repetida",
  "sem_leitura",
  "imagem_implausivel",
  "imagem_ilegivel",
  "valor_abaixo_do_esperado",
  "destino_desconhecido",
  "titular_divergente",
]

describe("vocabulário da suspeita", () => {
  it("tem rótulo e rejeição sugerida para todo motivo", () => {
    // Um buraco aqui devolveria `undefined` na tela — que é exatamente o defeito de origem.
    for (const motivo of TODOS) {
      expect(rotuloDaSuspeita[motivo]).toBeTruthy()
      expect(rejeicaoSugerida[motivo]).toBeTruthy()
    }
    expect(Object.keys(rotuloDaSuspeita).sort()).toEqual([...TODOS].sort())
    expect(Object.keys(rejeicaoSugerida).sort()).toEqual([...TODOS].sort())
  })

  it("só sugere rejeição que o diálogo oferece", () => {
    const oferecidos = motivoRejeicaoOptions.map((o) => o.value)
    for (const motivo of TODOS) {
      expect(oferecidos).toContain(rejeicaoSugerida[motivo])
    }
  })

  it("dá à montagem um veredito próprio, em vez de 'outro'", () => {
    expect(rejeicaoSugerida.imagem_implausivel).toBe("comprovante_falso")
    expect(motivoRejeicaoOptions.map((o) => o.value)).toContain("comprovante_falso")
  })

  it("oferece o vocabulário inteiro no filtro, com 'todos' na frente", () => {
    expect(motivoSuspeitaFiltroOptions[0].value).toBe("todos")
    expect(motivoSuspeitaFiltroOptions.slice(1).map((o) => o.value).sort()).toEqual(
      [...TODOS].sort()
    )
  })
})

describe("lerSuspeita", () => {
  it("separa o carimbo do detalhe", () => {
    const lida = lerSuspeita("valor_abaixo_do_esperado: valor extraido 80.00 < esperado R$100")
    expect(lida.motivo).toBe("valor_abaixo_do_esperado")
    expect(lida.detalhe).toBe("valor extraido 80.00 < esperado R$100")
    expect(lida.rotulo).toBe("Valor abaixo do esperado")
  })

  it("corta só no PRIMEIRO separador", () => {
    // A prosa do backend já usa ":" internamente.
    const lida = lerSuspeita("sem_leitura: vision inconclusivo: finish_reason=length")
    expect(lida.motivo).toBe("sem_leitura")
    expect(lida.detalhe).toBe("vision inconclusivo: finish_reason=length")
  })

  it("mostra a prosa antiga inteira em vez de nada", () => {
    // Fail-open: toda linha gravada antes do ticket 07 não tem carimbo. Antes disto o operador
    // via um parágrafo vazio; agora vê o motivo, ainda que sem etiqueta.
    const lida = lerSuspeita("chave divergente: extraida x, esperada y")
    expect(lida.motivo).toBeNull()
    expect(lida.rotulo).toBe("chave divergente: extraida x, esperada y")
    expect(lida.detalhe).toBe("chave divergente: extraida x, esperada y")
  })

  it("não aceita palavra qualquer como carimbo", () => {
    expect(lerSuspeita("bagunca: alguma coisa").motivo).toBeNull()
  })

  it("trata o comprovante sem motivo", () => {
    expect(lerSuspeita(null)).toEqual({ motivo: null, detalhe: "", rotulo: "" })
    expect(lerSuspeita("")).toEqual({ motivo: null, detalhe: "", rotulo: "" })
  })
})
