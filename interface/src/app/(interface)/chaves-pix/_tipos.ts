/**
 * A aba **Chaves Pix** (ticket 02, ADR-0049): o registro de "de quem é esta chave".
 *
 * Ela existe porque a pergunta que a operação faz diante de um comprovante tem quatro respostas e
 * o sistema só sabia dar duas — *está na lista da casa* ou *não está*. O "não está" engolia a
 * chave da própria modelo, que resolve em que bolso o dinheiro caiu (ADR-0047 §2), junto com a
 * chave de um terceiro qualquer; o aviso disparava igual nos dois até o gestor aprender a
 * ignorá-lo.
 *
 * Cada nome abaixo é o nome literal de `api/src/barra/dominio/financeiro/schemas.py`; divergir
 * aqui não quebra o build, quebra a tela em produção.
 *
 * ⚠️ Esta tela **não** é o cadastro `chave_pix` da ficha da modelo. Aquele campo tem um sentido só
 * — a chave preferida dela para **receber repasse** (ADR-0049 §3). Somar os dois sentidos faz um
 * repasse da casa **para** ela ser lido como uma venda **dela**, e o razão dobra.
 */

/** `barravips.papel_da_chave_enum`. `desconhecida` não está aqui: é a ausência de cadastro. */
export type PapelDaChave = "casa" | "modelo" | "telefonista" | "terceiro"

/** `GET /v1/financeiro/chaves-pix` → `ChavePixResponse`. */
export interface ChavePix {
  id: string
  chave: string
  /** Sem espaço, pontuação e sinal — a MESMA forma com que o OCR compara. */
  chave_normalizada: string
  papel: PapelDaChave
  modelo_id: string | null
  modelo_nome: string | null
  vendedor_id: string | null
  vendedor_nome: string | null
  titular: string | null
  descricao: string | null
  /** A UMA chave da casa que a operação usa por default. No máximo uma na lista inteira. */
  padrao: boolean
  ativo: boolean
}

export interface ChavesPixListaResponse {
  items: ChavePix[]
}

export const PAPEIS: PapelDaChave[] = ["casa", "modelo", "telefonista", "terceiro"]

export const ROTULO_DO_PAPEL: Record<PapelDaChave, string> = {
  casa: "Casa",
  modelo: "Modelo",
  telefonista: "Telefonista",
  terceiro: "Terceiro",
}

/**
 * O que cada papel significa para o dinheiro — a frase que o gestor lê antes de classificar.
 *
 * `terceiro` é o único que não atribui nada: ele existe para **parar de alarmar** sobre uma chave
 * legítima e conhecida (o fornecedor, a dívida pessoal dela), não para dizer de quem é o dinheiro.
 */
export const EXPLICACAO_DO_PAPEL: Record<PapelDaChave, string> = {
  casa: "Conta da operação. Dinheiro que cai aqui é da empresa.",
  modelo: "A chave dela. Dinheiro do cliente que cai aqui ficou com ela.",
  telefonista: "A conta dele — o caso do deslocamento que às vezes cai lá.",
  terceiro: "Legítima e conhecida, de ninguém do sistema. Só para parar de alarmar.",
}

/** `modelo` exige a modelo; `telefonista` exige o telefonista; os outros dois não aceitam dono. */
export function papelPedeDono(papel: PapelDaChave): "modelo" | "vendedor" | null {
  if (papel === "modelo") return "modelo"
  if (papel === "telefonista") return "vendedor"
  return null
}

/** O dono já resolvido em nome legível, ou `null` quando o papel não pede dono. */
export function donoDaChave(chave: ChavePix): string | null {
  return chave.modelo_nome ?? chave.vendedor_nome ?? null
}

// --- A fila de sugestões: chave desconhecida recorrente (ADR-0049 §5, ticket 05) ---------------

/** Em cujo grupo o comprovante apareceu — o "sempre recebendo da Yasmin" da sugestão. */
export interface ModeloQueMandou {
  id: string
  nome: string
}

/**
 * `GET /v1/financeiro/chaves-pix/sugestoes` → `SugestaoDeChavePixResponse`.
 *
 * Não é um cadastro pendente: é uma **pergunta** derivada dos comprovantes que já existem. Nada
 * aqui vira linha sem o gestor escolher o papel — sugestão nunca vira cadastro sozinha.
 *
 * A linha some da fila no instante em que a chave é cadastrada, porque a fila é uma consulta e não
 * uma tabela: cadastrar **é** o gesto que a remove.
 */
export interface SugestaoDeChave {
  /** A grafia mais recente que o OCR leu — é com ela que se confere a tela do banco. */
  chave: string
  chave_normalizada: string
  /** "Apareceu 4 vezes em 3 semanas, sempre recebendo da Yasmin — de quem é?" */
  pergunta: string
  vezes: number
  primeiro_em: string
  ultimo_em: string
  /** O tamanho da dúvida em reais — quanto já foi para este destino na janela. */
  valor_total_brl: number
  /** Os nomes que o OCR leu no destino. O primeiro vira o `titular` sugerido no formulário. */
  titulares: string[]
  modelos: ModeloQueMandou[]
  /**
   * Preenchido só quando UMA modelo mandou tudo. É palpite de DONO, nunca de papel: o formulário
   * não abre em `modelo` por causa dele — ele só evita redigitar a modelo quando o gestor escolhe
   * esse papel. Adivinhar o papel seria adivinhar de quem é o dinheiro, que é a pergunta.
   */
  modelo_id_sugerido: string | null
}

export interface SugestoesDeChaveListaResponse {
  items: SugestaoDeChave[]
}
