import { describe, expect, it } from "vitest"
import { categoriaEvento, descricaoEvento, iconeEvento } from "@/components/atendimentos/utils"
import type { EventoAtendimento } from "@/tipos/atendimentos"

function evento(parcial: Partial<EventoAtendimento>): EventoAtendimento {
  return {
    id: "e1",
    tipo: "transicao_estado",
    origem: "agente",
    autor: "IA",
    payload: {},
    created_at: "2026-06-17T20:46:51.231Z",
    ...parcial,
  }
}

describe("categoriaEvento", () => {
  it("trata extração da IA como telemetria", () => {
    expect(categoriaEvento("extracao_registrada")).toBe("telemetria")
  })
  it("trata os demais tipos como marco", () => {
    expect(categoriaEvento("transicao_estado")).toBe("marco")
    expect(categoriaEvento("atendimento_fechado")).toBe("marco")
  })
})

describe("iconeEvento", () => {
  it("mapeia famílias de tipo para a chave de ícone", () => {
    expect(iconeEvento("transicao_estado")).toBe("estado")
    expect(iconeEvento("pipeline_validado")).toBe("pix")
    expect(iconeEvento("bloqueio_criado")).toBe("bloqueio")
    expect(iconeEvento("extracao_registrada")).toBe("ia")
    expect(iconeEvento("tipo_desconhecido")).toBe("default")
  })
})

describe("descricaoEvento", () => {
  it("descreve a transição de estado em linguagem de negócio", () => {
    expect(descricaoEvento(evento({ tipo: "transicao_estado", payload: { para: "Aguardando_confirmacao" } })))
      .toBe("Avançou para Aguardando confirmação")
  })

  it("prioriza a próxima ação esperada (texto humano) na extração", () => {
    const desc = descricaoEvento(
      evento({
        tipo: "extracao_registrada",
        payload: {
          intencao: "agendamento",
          proxima_acao_esperada: "Cliente a caminho. Aguardar aviso de chegada.",
        },
      })
    )
    expect(desc).toBe("Cliente a caminho. Aguardar aviso de chegada.")
  })

  it("cai no resumo do payload quando não há próxima ação", () => {
    const desc = descricaoEvento(
      evento({ tipo: "extracao_registrada", payload: { intencao: "agendamento", tipo_atendimento: "interno" } })
    )
    expect(desc).toContain("intencao")
  })
})
