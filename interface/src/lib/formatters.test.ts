import { describe, expect, it } from 'vitest'

import { ehTelefoneExibivel, formatData, formatDuracaoHoras, nomeCliente } from './formatters'

describe('formatData', () => {
  it('date-only (data_desejada) mantém o dia — não recua para a véspera em BRT', () => {
    expect(formatData('2026-06-10')).toBe('10 de jun. de 2026')
  })

  it('timestamp completo segue convertendo para America/Sao_Paulo', () => {
    // 02:00Z de 11/06 = 23:00 de 10/06 em BRT
    expect(formatData('2026-06-11T02:00:00Z')).toBe('10 de jun. de 2026')
  })
})

describe('formatDuracaoHoras', () => {
  it('horas inteiras (numeric string do Postgres "12.00") viram "12h"', () => {
    expect(formatDuracaoHoras('12.00')).toBe('12h')
  })

  it('number inteiro vira "Nh"', () => {
    expect(formatDuracaoHoras(2)).toBe('2h')
  })

  it('meia hora vira "1h30"', () => {
    expect(formatDuracaoHoras('1.5')).toBe('1h30')
  })

  it('menos de uma hora vira "N min"', () => {
    expect(formatDuracaoHoras(0.5)).toBe('30 min')
  })

  it('null, zero e valores inválidos viram null', () => {
    expect(formatDuracaoHoras(null)).toBeNull()
    expect(formatDuracaoHoras(undefined)).toBeNull()
    expect(formatDuracaoHoras(0)).toBeNull()
    expect(formatDuracaoHoras('abc')).toBeNull()
  })
})

describe('ehTelefoneExibivel', () => {
  it('aceita E.164 BR (com e sem 55)', () => {
    expect(ehTelefoneExibivel('5512992609133')).toBe(true)
    expect(ehTelefoneExibivel('12992609133')).toBe(true)
  })

  it('rejeita JID de grupo e número de 18 dígitos', () => {
    expect(ehTelefoneExibivel('120363423572479616')).toBe(false)
    expect(ehTelefoneExibivel('120363423572479616@g.us')).toBe(false)
  })
})

describe('nomeCliente', () => {
  it('prioriza o nome quando há', () => {
    expect(nomeCliente('João', '120363423572479616')).toBe('João')
  })

  it('formata o telefone válido quando não há nome', () => {
    expect(nomeCliente(null, '5512992609133')).toBe('(12) 99260-9133')
  })

  it('usa rótulo neutro para JID/telefone inválido sem nome', () => {
    expect(nomeCliente(null, '120363423572479616')).toBe('Contato sem telefone')
  })
})
