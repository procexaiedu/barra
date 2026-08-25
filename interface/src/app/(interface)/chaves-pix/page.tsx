"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { KeyRound } from "lucide-react"
import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useModelosOpcoes } from "@/hooks/useModelosOpcoes"
import { api, ApiError } from "@/lib/api"
import { DialogNovaChave } from "./DialogNovaChave"
import { FilaDeSugestoes } from "./FilaDeSugestoes"
import { LinhaChavePix } from "./LinhaChavePix"
import type { OpcaoDeDono } from "./SeletorDePapel"
import type {
  ChavePix,
  ChavesPixListaResponse,
  SugestaoDeChave,
  SugestoesDeChaveListaResponse,
} from "./_tipos"

interface TelefonistasListaResponse {
  items: { id: string; nome: string }[]
}

/**
 * A aba **Chaves Pix** (ADR-0049): o registro de "de quem é esta chave".
 *
 * O que ela conserta: a pergunta que a operação faz diante de um comprovante tem quatro respostas,
 * e o sistema só sabia dar duas — *está na lista da casa* ou *não está*. O "não está" engolia a
 * chave da própria modelo, que resolve em que bolso o dinheiro caiu (ADR-0047 §2), junto com a
 * chave de um terceiro qualquer; o mesmo aviso disparava nos dois casos até o gestor aprender a
 * ignorá-lo.
 *
 * ⚠️ Nada aqui trava fluxo. Comprovante com destino fora do registro continua sendo processado e
 * abatendo o que tem que abater — o registro muda **o que o gestor vê**, não o que o sistema faz.
 *
 * ⚠️ Não existe excluir. Inativar nunca deletar: a chave aposentada continua explicando os
 * comprovantes antigos que apontam para ela.
 */
export default function ChavesPixPage() {
  const [lista, setLista] = useState<ChavePix[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [incluirInativas, setIncluirInativas] = useState(false)
  const [criarOpen, setCriarOpen] = useState(false)
  const [sugestoes, setSugestoes] = useState<SugestaoDeChave[]>([])
  // A sugestão que abriu o diálogo — `null` é o "Cadastrar chave" do cabeçalho, sem palpite algum.
  const [sugestaoEmFoco, setSugestaoEmFoco] = useState<SugestaoDeChave | null>(null)
  const [telefonistas, setTelefonistas] = useState<OpcaoDeDono[]>([])
  const { modelos } = useModelosOpcoes()

  const carregar = useCallback(async () => {
    try {
      const r = await api<ChavesPixListaResponse>(
        `/v1/financeiro/chaves-pix?incluir_inativas=${incluirInativas}`,
      )
      setLista(r.items)
      setErro(null)
    } catch (e) {
      setErro(e instanceof ApiError ? e.detail : "Erro ao carregar as chaves")
    }
  }, [incluirInativas])

  // A fila é DERIVADA dos comprovantes: recarregá-la depois de cadastrar é o que faz a linha
  // sumir — não há estado de sugestão para apagar em lugar nenhum.
  const carregarSugestoes = useCallback(async () => {
    try {
      const r = await api<SugestoesDeChaveListaResponse>("/v1/financeiro/chaves-pix/sugestoes")
      setSugestoes(r.items)
    } catch {
      // A fila é um extra: sem ela a aba continua sendo o cadastro. Um banner de erro aqui
      // competiria com o erro da lista, que é o que realmente impede o trabalho.
    }
  }, [])

  useEffect(() => {
    // `carregar` é async: os setState só rodam depois do await. Mesmo padrão da aba Telefonistas.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar()
  }, [carregar])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregarSugestoes()
  }, [carregarSugestoes])

  useEffect(() => {
    let cancelado = false
    api<TelefonistasListaResponse>("/v1/financeiro/telefonistas")
      .then((r) => {
        if (!cancelado) setTelefonistas(r.items)
      })
      .catch(() => {
        // Sem telefonistas o papel `telefonista` fica sem opções — a tela continua servindo os
        // outros três, que é o caso comum. Não vale um banner de erro.
      })
    return () => {
      cancelado = true
    }
  }, [])

  const opcoesModelos: OpcaoDeDono[] = useMemo(() => modelos ?? [], [modelos])

  const padrao = lista?.find((c) => c.padrao) ?? null
  const semPadrao = lista !== null && lista.some((c) => c.papel === "casa") && padrao === null

  // Trocar a marca de padrão mexe em DUAS linhas no servidor (a nova ganha, a antiga perde). A
  // lista local só sabe da que voltou na resposta, então aqui a fonte de verdade é o servidor.
  const trocar = (atualizada: ChavePix) =>
    setLista((atual) => (atual ?? []).map((c) => (c.id === atualizada.id ? atualizada : c)))

  const aposSalvar = (atualizada: ChavePix) => {
    if (!incluirInativas && !atualizada.ativo) {
      setLista((atual) => (atual ?? []).filter((c) => c.id !== atualizada.id))
      return
    }
    trocar(atualizada)
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Chaves Pix"
        description="De quem é cada chave — a casa, uma modelo, um telefonista ou um terceiro conhecido."
        action={{
          label: "Cadastrar chave",
          onClick: () => {
            setSugestaoEmFoco(null)
            setCriarOpen(true)
          },
          icon: <KeyRound size={16} strokeWidth={1.5} />,
        }}
      >
        <Button
          variant={incluirInativas ? "secondary" : "outline"}
          size="sm"
          aria-pressed={incluirInativas}
          onClick={() => setIncluirInativas((v) => !v)}
        >
          {incluirInativas ? "Mostrando inativas" : "Mostrar inativas"}
        </Button>
      </PageHeader>

      <FilaDeSugestoes
        sugestoes={sugestoes}
        onClassificar={(s) => {
          setSugestaoEmFoco(s)
          setCriarOpen(true)
        }}
      />

      <section className="flex flex-col gap-3">
        <p className="text-[12px] leading-relaxed text-text-muted">
          É este cadastro que faz o destino de um comprovante <strong>significar alguém</strong>. Um
          Pix que cai na chave da modelo não é o mesmo que um Pix que cai na chave de um
          desconhecido — sem o papel, o sistema avisa igual nos dois e o aviso perde o valor. Chave
          que não está aqui continua sendo aceita; ela só fica sem explicação.
        </p>

        {semPadrao && (
          <div className="rounded-lg border border-warn-500/40 bg-[color:var(--warn-500)]/8 px-4 py-3">
            <p className="text-[12.5px] text-text-primary">
              Nenhuma chave da casa está marcada como padrão. Não é erro — as outras recebem do
              mesmo jeito —, mas é a que a operação usa por default.
            </p>
          </div>
        )}

        {erro && lista === null && (
          <div className="rounded-lg border border-danger-500/40 bg-[color:var(--danger-500)]/8 px-4 py-3">
            <p className="text-[13px] text-text-primary">{erro}</p>
            <button
              type="button"
              onClick={carregar}
              className="mt-2 text-[12px] font-medium text-text-brand underline underline-offset-2"
            >
              Tentar de novo
            </button>
          </div>
        )}

        {lista === null && erro === null && <Skeleton className="h-[220px] w-full rounded-lg" />}

        {lista !== null &&
          (lista.length === 0 ? (
            <div className="rounded-lg bg-card px-4 py-10 text-center ring-1 ring-border-subtle">
              <p className="text-[13px] text-text-primary">Nenhuma chave cadastrada.</p>
              <p className="mt-1 text-[12px] text-text-muted">
                Comece pelas chaves da casa e marque a que a operação mais usa como padrão. As
                chaves das modelos podem entrar depois — inclusive várias por modelo.
              </p>
            </div>
          ) : (
            <ul
              aria-label="Chaves Pix"
              className="overflow-hidden rounded-lg bg-card ring-1 ring-border-subtle shadow-elev-1"
            >
              {lista.map((c) => (
                <LinhaChavePix
                  key={c.id}
                  chave={c}
                  modelos={opcoesModelos}
                  telefonistas={telefonistas}
                  onSalvo={aposSalvar}
                  onPadraoTrocada={carregar}
                />
              ))}
            </ul>
          ))}
      </section>

      <DialogNovaChave
        open={criarOpen}
        onOpenChange={setCriarOpen}
        modelos={opcoesModelos}
        telefonistas={telefonistas}
        sugestao={sugestaoEmFoco}
        onCriada={() => {
          carregar()
          carregarSugestoes()
        }}
      />
    </div>
  )
}
