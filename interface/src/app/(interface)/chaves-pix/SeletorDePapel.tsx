"use client"

import { Combobox } from "@/components/ui/combobox"
import { Segmented, SegmentedItem } from "@/components/ui/segmented"
import {
  EXPLICACAO_DO_PAPEL,
  PAPEIS,
  ROTULO_DO_PAPEL,
  papelPedeDono,
  type PapelDaChave,
} from "./_tipos"

export interface OpcaoDeDono {
  id: string
  nome: string
}

/**
 * Papel + dono, sempre juntos — que é como o backend os aceita.
 *
 * Trocar o papel **limpa o dono**, e isso não é conveniência de UI: `papel = casa` com um
 * `modelo_id` pendurado é uma linha com dois donos discordando, e o `PATCH` reescreve os dois
 * campos de uma vez justamente para que essa linha nunca exista.
 */
export function SeletorDePapel({
  papel,
  onPapel,
  donoId,
  onDono,
  modelos,
  telefonistas,
  idPrefixo,
  disabled,
  modeloSugerida,
}: {
  papel: PapelDaChave
  onPapel: (p: PapelDaChave) => void
  donoId: string | null
  onDono: (id: string | null) => void
  modelos: OpcaoDeDono[]
  telefonistas: OpcaoDeDono[]
  idPrefixo: string
  disabled?: boolean
  /**
   * Vindo de uma sugestão: a única modelo que mandou para esta chave. Preenche o combo **quando**
   * o gestor escolhe o papel `modelo` — não escolhe o papel por ele. Ele continua sendo o palpite
   * de quem, nunca o de quê, que é a pergunta que a sugestão faz.
   */
  modeloSugerida?: string | null
}) {
  const pede = papelPedeDono(papel)
  const opcoes = pede === "modelo" ? modelos : pede === "vendedor" ? telefonistas : []
  const nomePorId = new Map(opcoes.map((o) => [o.id, o.nome]))

  return (
    <div className="flex flex-col gap-2">
      <Segmented className="w-fit" aria-label="Papel da chave">
        {PAPEIS.map((p) => (
          <SegmentedItem
            key={p}
            active={papel === p}
            disabled={disabled}
            onClick={() => {
              if (papel === p) return
              onPapel(p)
              onDono(p === "modelo" ? (modeloSugerida ?? null) : null)
            }}
          >
            {ROTULO_DO_PAPEL[p]}
          </SegmentedItem>
        ))}
      </Segmented>

      <p className="text-[11px] text-text-muted">{EXPLICACAO_DO_PAPEL[papel]}</p>

      {pede !== null && (
        <div>
          <Combobox
            id={`${idPrefixo}-dono`}
            value={donoId ?? ""}
            onChange={(v) => onDono(v || null)}
            options={opcoes.map((o) => o.id)}
            displayFormat={(id) => nomePorId.get(id) ?? id}
            placeholder={pede === "modelo" ? "Escolha a modelo" : "Escolha o telefonista"}
            disabled={disabled}
          />
          {donoId === null && (
            <p className="mt-1 text-[11px] text-warn-500">
              {pede === "modelo"
                ? "Chave de modelo precisa dizer de qual modelo — sem isso ela não resolve bolso nenhum."
                : "Chave de telefonista precisa dizer de quem."}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
