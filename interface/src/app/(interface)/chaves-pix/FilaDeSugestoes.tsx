"use client"

import { HelpCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { formatBRL } from "@/lib/formatters"
import type { SugestaoDeChave } from "./_tipos"

/**
 * **De quem é esta chave?** — a fila que o uso preenche (ADR-0049 §5, ticket 05).
 *
 * O que ela conserta: o aviso "⚠️ esse Pix foi pra uma chave fora da lista da casa" disparava a
 * cada comprovante, e os casos legítimos se repetem toda semana — a modelo pagando uma dívida
 * pessoal, um fornecedor, a conta nova dela depois de trocar de banco. Um alarme que dispara
 * sempre para a mesma coisa deixa de ser alarme, e o gestor aprende a ignorá-lo.
 *
 * Agora o grupo fala **uma vez** (destino desconhecido recebendo dinheiro de venda pela primeira
 * vez) e a repetição vem parar aqui, onde ela vale mais: com contagem, período, valor e de quem
 * ela recebeu — tudo que a segunda foto no WhatsApp não conseguia dizer.
 *
 * ⚠️ **Sugestão nunca vira cadastro sozinha.** Não existe "aceitar todas": cada linha abre o mesmo
 * formulário de sempre, com um humano escolhendo o papel. O sistema honestamente não sabe se
 * aquela chave é a conta nova da modelo, um fornecedor ou um golpe — as três têm a mesma cara num
 * extrato.
 *
 * A lista não precisa ser limpa: ela é derivada dos comprovantes, então cadastrar a chave **é** o
 * gesto que tira a linha daqui.
 */
export function FilaDeSugestoes({
  sugestoes,
  onClassificar,
}: {
  sugestoes: SugestaoDeChave[]
  onClassificar: (s: SugestaoDeChave) => void
}) {
  if (sugestoes.length === 0) return null

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="text-[13px] font-medium text-text-primary">De quem é esta chave?</h2>
        <p className="mt-1 text-[12px] leading-relaxed text-text-muted">
          Destinos que apareceram <strong>mais de uma vez</strong> nos comprovantes e que o cadastro
          ainda não explica. Nada aqui foi cadastrado — são perguntas. Responder uma some com ela e
          passa a valer no próximo comprovante.
        </p>
      </div>

      <ul
        aria-label="Sugestões de chave"
        className="overflow-hidden rounded-lg bg-card ring-1 ring-border-subtle shadow-elev-1"
      >
        {sugestoes.map((s) => (
          <li
            key={s.chave_normalizada}
            className="flex flex-wrap items-center gap-3 border-b border-border-subtle px-4 py-3 last:border-b-0"
          >
            <HelpCircle size={16} strokeWidth={1.5} className="shrink-0 text-text-muted" />
            <div className="min-w-0 flex-1">
              <p className="truncate font-mono text-[13px] text-text-primary">{s.chave}</p>
              <p className="mt-0.5 text-[12px] text-text-muted">{s.pergunta}</p>
              <p className="mt-0.5 text-[11px] text-text-muted">
                {formatBRL(s.valor_total_brl)} no total
                {s.titulares.length > 0 && <> · titular lido: {s.titulares.join(", ")}</>}
              </p>
            </div>
            <Button size="sm" variant="outline" onClick={() => onClassificar(s)}>
              De quem é?
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}
