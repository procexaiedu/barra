import { describe, expect, it } from 'vitest'

import { formatData, formatDuracaoHoras } from './formatters'

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
