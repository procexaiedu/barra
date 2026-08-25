"""A rotina diaria da manha (spec 0005, ticket 10): UMA cobranca consolidada por grupo, por dia.

E o que tira o gestor do loop. Hoje e ele quem volta no grupo dias depois para perguntar "foi pix
ou din ?" venda por venda; a partir daqui quem faz isso e o agente — **uma vez por dia, numa
mensagem so**. O dominio e explicito sobre a forma: "cobranca de pendencia e CONSOLIDADA (na
rotina da manha — uma mensagem, nao uma pergunta por venda na hora, porque o atendimento pode nem
ter acontecido quando e anunciado)".

Tres decisoes moram aqui:

* **Silencio e o default.** Sem pendencia acionavel e sem movimento, o agente nao fala. Um "bom
  dia, nada a relatar" diario e exatamente o que torna um grupo inabitavel — e grupo inabitavel e
  o unico jeito de a operacao desligar o agente.
* **A cobranca NOMEIA a venda (cliente, valor, dia).** Nao e cortesia: e o que permite a resposta
  cair na venda certa. Quem le "foi pix ou dinheiro?" sem saber de qual atendimento responde
  qualquer coisa, e o modulo escreveria a forma na venda errada — que e o erro que nunca mais e
  descoberto (venda errada some do Fechamento e ninguem a cobra de novo).
* **Uma lista com teto.** Grupo com dez pendencias nao recebe dez linhas: as primeiras aparecem
  nomeadas e o resto vira uma linha de resumo. Consolidada quer dizer legivel, nao completa.
* **A Ficha sem desfecho e a terceira coisa cobrada** (ticket 10; ADR-0044). O telefonista postou o
  card, o atendimento aconteceu e ninguem disse que recebeu: a ficha envelhece ABERTA, e ficha
  esquecida e dinheiro perdido — ela nunca vira venda, entao nao aparece em nenhuma das colunas do
  extrato e ninguem sente falta dela. Aqui ela vira uma linha ("Ficha · Cliente Igor · R$ 700,00 ·
  ontem — rolou?"), no MESMO canal e na MESMA mensagem: e o que o ADR-0046 §5 promete quando so o
  ✅ chegou, e o que o ADR-0047 §3 ja faz com o bolso nao dito. Cobrar nao trava nada — quem
  responde entra pela porta unica, e la a resposta promove a ficha a Venda registrada (ticket 07).

**Escopo: MODELO, e a itemizacao junto com o saldo** (corrigido em 14/08, pelo replay do export).
Ha um Grupo financeiro por modelo, entao "o que este grupo cobra" e "o que esta modelo deve
responder" sao a mesma coisa — e as duas metades da fala precisam concordar. Enquanto a
itemizacao era do GRUPO (as vendas cuja mensagem-fonte esta nele) e o saldo da MODELO, o anuncio
de duas modelos quebrava as duas: a venda da parceira nasce ancorada no grupo de quem anunciou,
entao a Yasmin recebia "foi pix ou dinheiro?" sobre a venda da Julia — duas linhas identicas,
porque o valor de cada uma e o mesmo — enquanto o saldo abaixo delas so contava as dela.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from barra.dominio.grupo_financeiro.fechamento import Extrato
from barra.dominio.grupo_financeiro.ficha import FichaDeAgendamento
from barra.dominio.grupo_financeiro.modelos import VendaRegistrada
from barra.dominio.grupo_financeiro.recibo import formatar_reais

ZERO = Decimal("0.00")

MAX_VENDAS_NOMEADAS = 4
"""Quantas vendas a cobranca nomeia antes de resumir o resto.

Quatro linhas ainda se le de relance no WhatsApp; dez viram parede de texto e a gestora para de
ler a mensagem inteira — e a partir dai a cobranca consolidada nao cobra nada. O que sobra nao
some: vira uma linha com quantas e quanto, e continua pendente amanha.
"""

MAX_FICHAS_NOMEADAS = 3
"""Quantas fichas sem desfecho a cobranca nomeia antes de resumir o resto.

Um a menos que o teto das vendas, e de proposito: as duas listas entram na MESMA mensagem, e o
teto que importa e o dela inteira. Quatro vendas mais quatro fichas mais o comprovante mais a
cobranca da agencia sao dez linhas — a parede de texto que faz a gestora parar de ler, que e o
ponto em que a cobranca consolidada deixa de cobrar qualquer coisa.
"""

SAUDACAO = "☀️ Bom dia!"


@dataclass(frozen=True)
class MovimentoDoGrupo:
    """O que se mexeu no grupo na janela da rotina — dinheiro, nao conversa.

    Serve a UMA decisao: falar ou calar quando nao ha pendencia nenhuma. Mensagem social, sticker
    e conversa NAO sao movimento; venda registrada e comprovante lido, sim. Sem essa distincao o
    agente postaria saldo todo dia em grupo que so teve papo, que e o "bom dia, nada a relatar"
    que o dominio proibe.
    """

    vendas: int = 0
    valor: Decimal = ZERO
    comprovantes: int = 0

    @property
    def houve(self) -> bool:
        return bool(self.vendas or self.comprovantes)


def fichas_sem_desfecho(
    fichas: Sequence[FichaDeAgendamento], *, hoje: date
) -> tuple[FichaDeAgendamento, ...]:
    """As fichas que a rotina COBRA hoje — as que envelheceram sem virar venda nem morrer.

    Ordem preservada (a do repo: mais antiga primeiro), e o criterio e PUBLICO de proposito: o
    painel mostra "as fichas que ficaram sem desfecho" (user story 47) e a rotina cobra. Dois
    criterios para o mesmo conjunto seriam duas versoes do que esta aberto, discordando na frente
    do gestor — e a versao que ele acreditaria seria a errada, porque a outra ele nao ve.

    Tres cortes, cada um por um motivo diferente:

    * **Ficha morta nao e cobrada.** `aberta` cobre os dois desfechos — o ❌ (cancelada) e a
      promocao a Venda registrada (realizada). Cobrar o desfecho de uma ficha que ja teve desfecho
      e a pendencia orfa que este modulo se recusa a criar em qualquer lugar. O repo ja filtra o
      estado no SELECT; repetir o filtro aqui e o que mantem esta funcao total sobre qualquer
      lista — inclusive a que um teste ou o painel montar de outro jeito.
    * **So o que ja venceu.** `data < hoje`: a ficha de HOJE ainda vai acontecer, e perguntar
      "rolou?" sobre um combinado da noite de hoje as 8h da manha e a metralhadora de perguntas
      que o dominio proibe — com o agravante de gastar a unica mensagem do dia.
    * **Ficha sem data nao e cobrada.** A que nasceu de um comunicado nao diz quando, e o modulo
      nao tem outro relogio para ela aqui (`FichaDeAgendamento` nao carrega `created_at`). Sem
      dia nao da para saber se ela venceu, e a linha nem poderia nomear o "ontem" que faz a
      resposta cair no lugar certo. Ela continua visivel no painel e continua respondivel no
      grupo; o que ela nao faz e virar pergunta no escuro.
    """
    return tuple(
        ficha for ficha in fichas if ficha.aberta and ficha.data is not None and ficha.data < hoje
    )


def montar_cobranca_da_manha(
    *,
    extrato: Extrato,
    a_cobrar: Sequence[VendaRegistrada],
    movimento: MovimentoDoGrupo,
    hoje: date,
    fichas: Sequence[FichaDeAgendamento] = (),
) -> str | None:
    """A UNICA mensagem que a rotina posta neste grupo hoje. `None` = silencio.

    `a_cobrar` sao as vendas DESTE grupo sem forma de pagamento dita (a Pendencia mais comum),
    da mais antiga para a mais nova; `extrato` e o Fechamento da modelo, o mesmo que o grupo ve
    sob comando (ticket 09) — usar dois caminhos ate o saldo seria dar ao gestor duas versoes do
    unico numero que ele confere de cabeca.

    `fichas` sao as Fichas de agendamento abertas DA MODELO (nao do grupo: ADR-0046 §2), como o
    repo as devolve. Quem filtra o que ja venceu e `fichas_sem_desfecho`, aqui dentro — passar a
    lista crua e o certo, porque o corte por data depende de `hoje`, que quem chama nem sempre
    tem. Default vazio para o caminho de quem ainda nao le ficha nenhuma continuar valendo.

    Divergencia NAO entra aqui de proposito. Ela ja virou pergunta no grupo no instante em que
    apareceu (o comprovante retido, ticket 07); repeti-la toda manha ate alguem responder e a
    metralhadora de perguntas que o dominio proibe. Ela continua visivel no fechamento sob
    comando e no painel.
    """
    cobrancas = _linhas_de_cobranca(
        extrato=extrato, a_cobrar=a_cobrar, fichas=fichas_sem_desfecho(fichas, hoje=hoje), hoje=hoje
    )
    if not cobrancas:
        # Nada que este grupo possa resolver respondendo. Se houve dinheiro na janela, o saldo
        # fecha o dia em uma linha; se nao houve, o agente nao tem o que dizer.
        return _fala_do_movimento(extrato=extrato, movimento=movimento) if movimento.houve else None

    # O saldo existe para dar TAMANHO a cobranca — e com nada vendido ele nao da tamanho nenhum:
    # "📊 Em aberto: R$ 0,00 de R$ 0,00 vendidos" logo abaixo de "Ficou pendente:" e a mensagem se
    # contradizendo em duas linhas. So virou caso real quando a Ficha entrou (ticket 10): ela e a
    # unica pendencia que nao e derivada de uma venda, entao e a primeira que aparece sozinha num
    # extrato zerado — o atendimento existe e o modulo ainda nao tem numero nenhum sobre ele.
    linhas = [f"{SAUDACAO} Ficou pendente:", *cobrancas]
    if extrato.vendido > ZERO:
        linhas.append(_linha_do_saldo(extrato))
    return "\n".join(linhas)


def _linhas_de_cobranca(
    *,
    extrato: Extrato,
    a_cobrar: Sequence[VendaRegistrada],
    fichas: Sequence[FichaDeAgendamento],
    hoje: date,
) -> list[str]:
    """O que o agente cobra hoje — forma de pagamento, venda a venda, e o comprovante em bloco.

    A forma vai nomeada porque a resposta precisa achar a venda; o comprovante vai agregado
    porque a resposta dele nao e texto, e uma FOTO — e o abate dela e FIFO por modelo (ticket
    07), entao dizer "o comprovante da venda do Gabriel" prometeria um casamento que o modulo
    nao faz.
    """
    # As NOMEADAS sao as mais RECENTES, e o resto (mais antigo) vai no resumo. `a_cobrar` chega
    # antiga->nova, entao o corte e no fim da lista.
    #
    # Foi o contrario ate 14/08, e o replay do export mostrou o estrago no dia 7 de operacao: a
    # fila nao anda (venda sem forma de pagamento fica aberta ate alguem falar), entao nomear as
    # primeiras faz o agente repetir TODA manha as mesmas quatro vendas mais velhas — justamente
    # as que ninguem respondeu e provavelmente nao vai responder — enquanto a venda de ontem, que
    # a gestora ainda lembra e responde em dois segundos, desaparece no "e mais N". Um mes assim e
    # uma mensagem diaria imutavel, que e como um agente de grupo morre: ninguem le mais.
    recentes = a_cobrar[-MAX_VENDAS_NOMEADAS:]
    resto = a_cobrar[: len(a_cobrar) - len(recentes)]
    linhas = [_linha_da_venda(venda, hoje) for venda in recentes]
    if resto:
        total = sum((venda.valor for venda in resto), ZERO)
        # A JANELA vai junto ("de 07/08 a 10/08"): o resumo tem que dizer que o que sobrou e
        # antigo. Sem isso, "e mais 3 vendas" e um numero sem tempo, e a gestora nao consegue
        # decidir se aquilo e coisa de ontem ou divida velha para resolver no painel.
        janela = _janela(resto, hoje)
        linhas.append(
            f"❓ E mais {len(resto)} venda{'s' if len(resto) > 1 else ''} sem forma de pagamento "
            f"{janela} ({formatar_reais(total)})."
        )

    # As FICHAS vem depois das vendas: as de cima sao dinheiro que o modulo JA registrou e so
    # nao sabe conciliar; a ficha e um atendimento que talvez nem tenha acontecido. Misturar as
    # duas listas faria a mais incerta herdar a autoridade da mais certa.
    linhas.extend(_linhas_das_fichas(fichas, modelo_id=extrato.modelo_id, hoje=hoje))

    comprovantes = sum(1 for p in extrato.pendencias if p.tipo == "comprovante")
    if comprovantes:
        linhas.append(
            f"📸 Falta o comprovante de {formatar_reais(extrato.a_comprovar)} "
            f"({comprovantes} venda{'s' if comprovantes > 1 else ''} em pix)."
        )

    cobranca = _linha_da_cobranca_da_agencia(extrato)
    if cobranca is not None:
        linhas.append(cobranca)
    return linhas


def _linhas_das_fichas(
    fichas: Sequence[FichaDeAgendamento], *, modelo_id: UUID, hoje: date
) -> list[str]:
    """As fichas sem desfecho, nomeadas ate o teto e resumidas depois dele.

    Mesmo corte das vendas e pelo mesmo motivo: as NOMEADAS sao as mais RECENTES. A fila da ficha
    tambem nao anda sozinha (ela so morre por resposta, ✅ ou ❌), entao nomear as mais antigas
    faria o agente repetir toda manha as mesmas tres que ninguem respondeu — enquanto a ficha de
    ontem, a unica que alguem ainda lembra, sumiria no "e mais N".
    """
    recentes = fichas[-MAX_FICHAS_NOMEADAS:]
    resto = fichas[: len(fichas) - len(recentes)]
    linhas = [_linha_da_ficha(ficha, modelo_id=modelo_id, hoje=hoje) for ficha in recentes]
    if resto:
        total = sum((f.valor_de(modelo_id) or ZERO for f in resto), ZERO)
        quantas = f"{len(resto)} ficha{'s' if len(resto) > 1 else ''} sem desfecho"
        janela = _janela_de_datas([f.data for f in resto if f.data is not None], hoje)
        # O valor so entra quando existe: ficha sem valor da participante e comum (o card do
        # telefonista pode trazer so o total da festinha), e "(R$ 0,00)" diria que o que sobrou
        # nao vale nada — exatamente o oposto do que a linha existe para dizer.
        valor = f" ({formatar_reais(total)})" if total > ZERO else ""
        linhas.append(f"❓ {' '.join(p for p in (f'E mais {quantas}', janela) if p)}{valor}.")
    return linhas


def _linha_da_ficha(ficha: FichaDeAgendamento, *, modelo_id: UUID, hoje: date) -> str:
    """ "❓ Ficha · Cliente Igor · R$ 700,00 · ontem — rolou? foi pix ou dinheiro?"

    Tres coisas na forma desta linha, e nenhuma e estetica:

    * **"Ficha" na frente** — a linha da venda tem a mesma gramatica (cliente · valor · dia) e
      faz outra pergunta. Sem o rotulo, a gestora le duas cobrancas identicas sobre o mesmo
      cliente (a venda ja registrada e a ficha que ainda nao virou venda) e responde uma so.
    * **O valor e o DELA** (`valor_de`), nunca o `valor_total`: numa festinha de R$ 2.000 com tres
      modelos, ecoar 2.000 no grupo de uma delas entrega a conta das outras. Quando a ficha nao
      diz o valor da participante, a linha sai sem valor — cliente e dia ainda identificam o
      atendimento, e inventar um numero e pior do que omiti-lo.
    * **A pergunta pede a FORMA junto** ("rolou? foi pix ou dinheiro?"). "Rolou?" sozinho colhe um
      "sim" que nao promove nada: a Venda registrada nasce no pagamento (ADR-0044 §2) e a forma
      vem de quem a disser (ADR-0046 §5). Pedir as duas coisas numa pergunta so e o que faz uma
      resposta unica fechar o ciclo — e evita a segunda pergunta, que e a metralhadora proibida.
    """
    identidade = ["Ficha"]
    if ficha.cliente_nome:
        identidade.append(f"Cliente {ficha.cliente_nome}")
    valor = ficha.valor_de(modelo_id)
    if valor is not None:
        identidade.append(formatar_reais(valor))
    if ficha.data is not None:
        identidade.append(_quando(ficha.data, hoje))
    return f"❓ {' · '.join(identidade)} — rolou? foi pix ou dinheiro?"


def _linha_da_cobranca_da_agencia(extrato: Extrato) -> str | None:
    """ "💸 Falta pagar a agência: R$ 385,80 (3RJ Suporte/Anúncio: 3 DIAS) — manda o comprovante."

    Por ULTIMO na cobranca porque e o outro eixo: as linhas de cima sao sobre o dinheiro que ela
    RECEBEU, esta e sobre o que ela DEVE. E ela e o motivo de a Cobranca da agencia ser rastreada
    (user story 10): tirar do gestor o trabalho de lembrar a modelo todo dia.

    Repete todo dia ate o comprovante chegar, e isso nao e metralhadora: e a MESMA mensagem
    consolidada de sempre, uma por dia, e some sozinha no dia em que a divida for paga. Uma
    cobranca vai nomeada, varias viram contagem — mesma regra do teto de vendas nomeadas.
    """
    if not extrato.cobrancas:
        return None
    if len(extrato.cobrancas) == 1:
        (cobranca,) = extrato.cobrancas
        return (
            f"💸 Falta pagar a agência: {formatar_reais(cobranca.valor)} "
            f"({cobranca.descricao}) — manda o comprovante quando pagar."
        )
    quantas = len(extrato.cobrancas)
    return (
        f"💸 Falta pagar a agência: {formatar_reais(extrato.debito)} "
        f"({quantas} cobranças) — manda o comprovante quando pagar."
    )


def _janela(vendas: Sequence[VendaRegistrada], hoje: date) -> str:
    """ "de 07/08 a 10/08", ou "de 07/08" quando as que sobraram sao todas do mesmo dia."""
    return _janela_de_datas([venda.data for venda in vendas], hoje)


def _janela_de_datas(datas: Sequence[date], hoje: date) -> str:
    """A janela de um resumo, seja ele de vendas ou de fichas — uma frase so para as duas.

    `min`/`max` em vez de primeira/ultima da lista: as duas listas chegam ordenadas, mas o resumo
    e sobre QUANDO, e uma janela que depende da ordem do SELECT mente calada no dia em que alguem
    mudar o `ORDER BY`. Lista vazia devolve `""`, que o chamador simplesmente nao concatena.
    """
    if not datas:
        return ""
    primeira, ultima = min(datas), max(datas)
    if primeira == ultima:
        return f"de {_quando(primeira, hoje)}"
    return f"de {_quando(primeira, hoje)} a {_quando(ultima, hoje)}"


def _linha_da_venda(venda: VendaRegistrada, hoje: date) -> str:
    """ "❓ Cliente Gabriel · R$ 700,00 · ontem — foi pix ou dinheiro?"

    Cliente e texto livre e pode nao ter sido dito; quando falta, valor + dia ainda identificam a
    venda para quem estava la. O que nunca sai e a pergunta: e ela que a resposta responde.
    """
    identidade = [formatar_reais(venda.valor), _quando(venda.data, hoje)]
    if venda.cliente_nome:
        identidade.insert(0, f"Cliente {venda.cliente_nome}")
    return f"❓ {' · '.join(identidade)} — foi pix ou dinheiro?"


def _linha_do_saldo(extrato: Extrato) -> str:
    """O saldo ABERTO, resumido: o que ainda nao fechou, contra o que ja foi vendido.

    Aberto = falta comprovar + sem forma. Nao e um extrato de quatro linhas (isso e o fechamento
    sob comando): a rotina cobra, e o saldo aqui existe para dar tamanho a cobranca.
    """
    aberto = extrato.a_comprovar + extrato.sem_forma
    return (
        f"📊 Em aberto: {formatar_reais(aberto)} "
        f"de {formatar_reais(extrato.vendido)} vendidos "
        f"({formatar_reais(extrato.comprovado)} já comprovados)."
    )


def _fala_do_movimento(*, extrato: Extrato, movimento: MovimentoDoGrupo) -> str:
    """Houve dinheiro e nao ha o que cobrar: uma linha, e so."""
    plural = "s" if movimento.vendas != 1 else ""
    vendas = f"{movimento.vendas} venda{plural} ({formatar_reais(movimento.valor)})"
    if extrato.conciliado:
        return f"{SAUDACAO} Ontem: {vendas} — tudo conciliado por aqui."
    return f"{SAUDACAO} Ontem: {vendas}.\n{_linha_do_saldo(extrato)}"


def _quando(dia: date, hoje: date) -> str:
    """ "ontem" para o dia anterior, "dd/mm" para o resto.

    O grupo fala assim ("O Lucas de ontem") e a rotina roda de manha, entao a venda mais cobrada
    e sempre a da vespera. Data crua para o resto: "ha 3 dias" obrigaria a gestora a fazer conta
    para achar o atendimento.
    """
    if dia == hoje - timedelta(days=1):
        return "ontem"
    return f"{dia:%d/%m}"


def chave_da_fala_do_dia(grupo_id: UUID, dia: date) -> str:
    """A chave de idempotencia da rotina: um grupo, um dia (BRT), uma fala.

    Vive na MESMA coluna `chave_dedup` que absorve a entrega duplicada do webhook, porque o
    problema e o mesmo: o processo pode rodar duas vezes (retry do cron, redeploy do worker, dois
    workers no Swarm) e quem garante uma unica fala tem que ser o banco, nao a agenda. O dia e o
    dia de BRASILIA — a janela da manha e a do grupo, nao a do UTC.
    """
    return f"rotina:{grupo_id}:{dia:%Y-%m-%d}"
