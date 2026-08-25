"""A PORTA UNICA do Agente financeiro (spec 0005, "Seam unico"; generalizada na spec 0006).

Espelho do `processar_turno` do agente de venda: um evento de Grupo financeiro entra, os efeitos
saem. Webhook, testes e o futuro replay do export do grupo chamam `processar_evento_do_grupo` — e
por isso o comportamento testado e o comportamento de producao (licao do harness fiel: quem testa
por dentro do grafo testa um agente que nao existe).

EVENTO, e nao mensagem: num grupo acontecem a MENSAGEM (conteudo novo) e os GESTOS sobre uma
mensagem que ja existe — apagar, reagir, editar. Os tres gestos tem a mesma forma (nao ha texto
novo, o dado util e QUAL mensagem foi tocada) e por isso entram pela mesma funcao, que roteia por
tipo. Hoje so a delecao tem comportamento; reacao e edicao existem no TIPO e caem no ramo que
ignora com log, do jeito que grupo nao cadastrado ja cai.

O que a porta faz hoje com uma MENSAGEM, em ordem:
  * roteia (grupo cadastrado e ativo? senao ignora com log — o numero e compartilhado com o
    myEYE) e PERSISTE a mensagem com origem completa, absorvendo entrega duplicada;
  * OUVE o audio (transcricao) e segue com o texto dele como se tivesse sido digitado — a modelo
    responde falando, e "foi pix" falado tem que valer o mesmo que escrito;
  * TRIA barato: eco do proprio agente e mensagem social (conversa, sticker) morrem aqui, sem
    custar extracao e sem resposta;
  * LE o anuncio, resolve as modelos closed-world e lanca a **Venda registrada** DIRETO
    (ADR-0043) — sem "posso lancar?" — postando o recibo curto, que e a porta de correcao;
    anuncio de duas modelos ("1300 cada uma") vira UMA linha por modelo, cada uma no valor dela;
  * DEDUPLICA por conteudo: o mesmo anuncio postado no grupo da outra participante, ou
    repostado depois de apagado, nao vira linha nova — o agente avisa curto que ja registrou;
  * quando o anuncio NAO fecha o minimo (modelo + valor + data), faz **uma** pergunta objetiva no
    grupo e fica esperando: a resposta ("600", "é a Duda") completa o registro e o recibo sai —
    e um **Nome de anuncio** aprendido assim vira cadastro, entao o mesmo nome nao e perguntado
    de novo;
  * absorve a **forma de pagamento** dita em qualquer mensagem, mesmo dias depois do anuncio
    ("O Lucas de ontem" / "Foi pix também amiga ?" / "Sim"), ligando-a a venda certa;
  * aceita a **correcao por quote** no recibo ("foi 650", "o cliente era Ramon"): atualiza a
    Venda registrada na hora, ecoa o de→para e deixa evento de auditoria;
  * LE por OCR o **Comprovante de transferencia** que a modelo posta e abate com ele as vendas
    pix abertas mais antigas dela (FIFO, saldo corrente continuo), confirmando curto o que ainda
    falta comprovar; comprovante que nao casa com venda nenhuma fica RETIDO com uma pergunta (e
    nao some), destino fora das chaves conhecidas da casa vira aviso ao gestor sem travar o
    abate, e imagem ilegivel vira um pedido de reenvio;
  * registra a **Cobranca da agencia** que o gestor posta ("*3RJ Suporte/Anuncio:* 3 DIAS |
    R$ 385,80") como DEBITO da modelo — nunca receita — e a quita quando o comprovante do
    pagamento chega, abatendo a cobranca e **nenhuma venda**; o Pix que serviria para os dois
    eixos fica retido com a pergunta que nomeia a cobranca candidata;
  * guarda CALADO o **Dado cadastral** que passa pelo grupo ("Torre 2 Apt 2706", a chave Pix que a
    propria modelo dita): sem responder, sem nunca perguntar por cadastro e com o valor anterior
    preservado para auditoria — painel-only, longe da ficha que a IA de venda le;
  * responde ao **pedido de fechamento** ("fechamento", "confere aí") com o extrato de tres
    colunas da modelo — vendido, comprovado (pix) e em especie — mais a diferenca que falta
    comprovar, as pendencias abertas e as divergencias como pergunta. Leitura pura: pedir o
    fechamento nao escreve nada e nao fecha periodo nenhum.

O outro gesto de correcao do grupo e apagar a mensagem e repostar. A delecao nao e mensagem (nao
tem texto, nem autor que disse algo) e por isso e um RAMO da porta, com tipo proprio — mas entra
pela mesma funcao, sai no mesmo `ResultadoDaPorta` e e testada do mesmo jeito. Depois dela, o repost entra como anuncio normal: se a versao repostada for identica, ela
volta a registrar (a linha anulada nao segura mais a chave de conteudo); se for diferente, e uma
venda nova. Nos dois casos sobra UM registro vivo.

O estado desses vai-e-vens NAO mora em lugar nenhum novo: e derivado do log de origem que o
ticket 01 ja guarda (`mensagens_recentes`). Estado derivado sobrevive a restart do worker e nao
tem o que reconciliar quando o grupo apaga ou reposta uma mensagem.

O que ela ainda NAO faz, e por que fica visivel em `motivo` em vez de virar palpite: nome ambiguo
continua no silencio (repetir o nome nao desempata homonimo), e o pagamento de Cobranca da agencia
para uma chave que nao e a da agencia passa sem alarme — o modulo conhece as chaves da CASA, nao
as dela (ver `_conciliar_com_cobranca`).

A pendencia que esta porta deixa aberta em silencio (forma de pagamento nao dita, comprovante que
nao chegou) e cobrada uma vez por dia pela rotina da manha (`agente_financeiro.rotina`, ticket
10), que nasce de relogio e nao de mensagem — a resposta dela volta por AQUI, como qualquer outra
fala do grupo.

`processar_mensagem_do_grupo` e `processar_delecao_do_grupo` continuam existindo como wrappers
finos sobre a porta unica: sao a entrada historica de 88 call sites e nao ha motivo para mexer em
nenhum deles so porque a porta ficou mais alta.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import UUID

from psycopg import AsyncConnection

from barra.agente_financeiro.comprovante import LerComprovante
from barra.agente_financeiro.leitura import IntencaoDoGrupo, LerIntencao
from barra.agente_financeiro.transcricao import TranscreverAudio
from barra.core.metrics import (
    GRUPO_FINANCEIRO,
    GRUPO_FINANCEIRO_ANUNCIOS,
    GRUPO_FINANCEIRO_AUDIO,
    GRUPO_FINANCEIRO_COMPROVANTES,
)
from barra.dominio.grupo_financeiro.anuncio import (
    AnuncioDeVenda,
    extrair_anuncio,
    ler_valor_avulso,
    normalizar,
    parece_anuncio_de_venda,
)
from barra.dominio.grupo_financeiro.bolso import (
    PREFIXO_DA_PERGUNTA_DO_BOLSO,
    BolsoResolvido,
    VendaComBolso,
    confrontar_bolso,
    montar_pergunta_do_bolso,
    montar_recibo_do_bolso,
    resolver_bolso,
)
from barra.dominio.grupo_financeiro.cobranca import (
    CasamentoDaCobranca,
    chave_de_conteudo_da_cobranca,
    escolher_cobranca,
    ler_cobranca,
    montar_aviso_de_cobranca_duplicada,
    montar_confirmacao_de_quitacao,
    montar_pergunta_do_comprovante_ambiguo,
    montar_recibo_da_cobranca,
)
from barra.dominio.grupo_financeiro.comprovante import (
    PEDIDO_DE_REENVIO,
    Classificacao,
    LeituraDoComprovante,
    PapelResolvido,
    PlanoDeAbate,
    deve_avisar_destino_fora_da_casa,
    e_do_cliente_para_a_casa,
    montar_aviso_de_chave_desconhecida,
    montar_aviso_de_cliente_para_a_casa,
    montar_aviso_de_comprovante_repetido,
    montar_aviso_de_entrada_da_modelo,
    montar_confirmacao_de_abate,
    montar_pergunta_do_comprovante,
    papel_da_chave,
    planejar_abate,
)
from barra.dominio.grupo_financeiro.correcao import (
    AVISO_DE_CORRECAO_AMBIGUA,
    AVISO_DE_CORRECAO_DUPLICADA,
    CAMPOS_DA_LINHA,
    CampoCorrigivel,
    Mudanca,
    aplicar_correcao,
    ler_correcao,
    montar_eco_de_correcao,
    mudancas_entre,
)
from barra.dominio.grupo_financeiro.dados_cadastrais import (
    DadoCadastralRegistrado,
    autor_e_a_modelo,
    e_a_chave_da_modelo,
    ler_dado_cadastral,
    montar_aviso_de_chave_da_modelo,
    nome_e_da_modelo,
)
from barra.dominio.grupo_financeiro.dedup import chave_de_conteudo
from barra.dominio.grupo_financeiro.fechamento import (
    Extrato,
    e_pedido_de_fechamento,
    montar_fala_do_fechamento,
)
from barra.dominio.grupo_financeiro.ficha import (
    PREFIXO_DA_DIVERGENCIA,
    PREFIXO_DO_COMUNICADO,
    DivergenciaDeDona,
    FichaDeAgendamento,
    FichaLida,
    OrigemDaPromocao,
    PlanoDaFicha,
    candidatas_do_comunicado,
    casar_comunicado,
    chave_de_conteudo_da_ficha,
    ler_ficha,
    montar_pergunta_da_divergencia,
    montar_pergunta_do_comunicado_ambiguo,
    parece_ficha_do_telefonista,
    planejar_ficha,
    planejar_promocao,
)
from barra.dominio.grupo_financeiro.gesto import PORTA_DA_REACAO, PORTA_DO_PAGAMENTO
from barra.dominio.grupo_financeiro.modelos import (
    AUDIO_SEM_TRANSCRICAO,
    AudioDoGrupo,
    DelecaoNoGrupo,
    FormaPagamento,
    GrupoFinanceiro,
    GrupoSemDona,
    ImagemDoGrupo,
    MensagemDoGrupo,
    MensagemRegistrada,
    VendaRegistrada,
)
from barra.dominio.grupo_financeiro.pagamento import (
    PREFIXO_DO_DESEMPATE,
    FalaDePagamento,
    escolher_ficha,
    escolher_pagamento,
    escolher_venda_do_bolso,
    ler_fala_de_bolso,
    ler_fala_de_pagamento,
    montar_pergunta_de_desempate,
    montar_pergunta_de_desempate_de_fichas,
    montar_recibo_da_promocao,
)
from barra.dominio.grupo_financeiro.pendencia import Pendencia, pendencias_da_venda
from barra.dominio.grupo_financeiro.pergunta import PREFIXO_DA_PERGUNTA, montar_pergunta_minima
from barra.dominio.grupo_financeiro.rateio import LinhaDoAnuncio, PlanoDoAnuncio, planejar
from barra.dominio.grupo_financeiro.recibo import (
    formatar_reais,
    montar_aviso_de_duplicata,
    montar_pergunta_de_anulacao,
    montar_recibo,
    montar_recibo_de_anulacao,
    montar_recibo_de_pagamento,
    montar_recibo_de_pagamento_coletivo,
)
from barra.dominio.grupo_financeiro.repo import (
    abater_vendas,
    ajustar_abate,
    anular_cobrancas_da_mensagem,
    anular_comprovantes_da_mensagem,
    anular_lancamentos_manuais_da_mensagem,
    anular_venda,
    buscar_grupo_cadastrado_por_jid,
    carregar_cadastro_de_nomes,
    cobranca_por_chave_de_conteudo,
    cobrancas_abertas_da_modelo,
    comprovante_por_conteudo,
    corrigir_lancamento_manual,
    corrigir_venda,
    dado_cadastral_atual,
    definir_bolso_da_venda,
    definir_forma_de_pagamento,
    ficha_aberta_da_mensagem_citada,
    ficha_por_chave_de_conteudo,
    fichas_abertas_da_modelo,
    gravar_nomes_de_anuncio,
    gravar_texto_da_mensagem,
    lancamento_manual_por_chave_de_conteudo,
    lancamentos_manuais_da_mensagem_citada,
    marcar_ficha_realizada,
    marcar_mensagem_apagada,
    mensagens_recentes,
    percentual_de_repasse,
    quitar_cobranca,
    registrar_cobranca,
    registrar_comprovante,
    registrar_dado_cadastral,
    registrar_evento_da_ficha,
    registrar_evento_do_bolso,
    registrar_eventos_da_venda,
    registrar_ficha,
    registrar_lancamento_manual,
    registrar_mensagem,
    registrar_venda,
    registrar_venda_da_ficha,
    registro_de_chaves,
    texto_da_mensagem_citada,
    venda_aberta_da_mensagem_citada,
    venda_para_o_bolso,
    venda_por_chave_de_conteudo,
    vendas_da_mensagem,
    vendas_da_mensagem_citada,
    vendas_para_o_bolso,
    vendas_pix_a_comprovar,
    vendas_sem_forma_de_pagamento,
    vezes_que_o_destino_apareceu,
)
from barra.dominio.grupo_financeiro.service import extrato_da_modelo
from barra.dominio.grupo_financeiro.temporada import LancamentoManual
from barra.dominio.grupo_financeiro.vale import (
    DESCRICAO_PADRAO as DESCRICAO_PADRAO_DO_VALE,
)
from barra.dominio.grupo_financeiro.vale import (
    ValeHesitante,
    chave_de_conteudo_do_vale,
    e_pergunta_do_vale,
    ler_vale,
    montar_aviso_de_vale_duplicado,
    montar_pergunta_do_vale,
    montar_recibo_do_vale,
)
from barra.dominio.grupo_financeiro.voz import e_fala_do_agente
from barra.webhook.parser import DelecaoEvolution, MensagemEvolution

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReacaoNoGrupo:
    """Alguem reagiu a uma mensagem que ja existe (o ✅/❌ do telefonista, spec 0006).

    Irmao da `DelecaoNoGrupo`, e nao um `MensagemDoGrupo` de tipo especial, pelo mesmo motivo dela:
    nada aqui e conteudo novo — o dado util e QUAL mensagem recebeu QUAL emoji, de quem. Existe
    hoje so no TIPO: a porta reconhece e ignora com log (ver `_ignorar_gesto`). O comportamento
    nasce no ticket que promover a Ficha de agendamento pelo ✅.

    Mora aqui, e nao em `dominio.grupo_financeiro.modelos` ao lado da delecao, porque ainda nao ha
    dominio nenhum pendurado nela: quando houver, muda de casa junto com a regra.
    """

    grupo_jid: str
    evolution_message_id: str
    """A mensagem ALVO da reacao — a que ja estava no grupo, nunca a reacao em si."""
    emoji: str = ""
    autor_jid: str | None = None
    de_mim: bool = False
    ocorrida_em: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class EdicaoNoGrupo:
    """Alguem editou uma mensagem que ja existe ("editada" do WhatsApp).

    Mesma forma da delecao e da reacao: gesto sobre uma mensagem que ja existe. O dado util e QUAL
    mensagem mudou e para QUAL texto. Tambem so existe no TIPO por enquanto — a porta ignora com
    log, e nada do que nasceu da versao antiga e mexido.
    """

    grupo_jid: str
    evolution_message_id: str
    """A mensagem ALVO da edicao — a chave que ja esta no log de origem."""
    texto: str = ""
    """O texto DEPOIS da edicao."""
    autor_jid: str | None = None
    de_mim: bool = False
    ocorrida_em: datetime = field(default_factory=lambda: datetime.now(UTC))


EventoDoGrupo = MensagemDoGrupo | DelecaoNoGrupo | ReacaoNoGrupo | EdicaoNoGrupo
"""Tudo que acontece num Grupo financeiro, do ponto de vista da porta: a MENSAGEM (conteudo novo)
e os GESTOS sobre uma mensagem que ja existe (apagar, reagir, editar).

E a uniao que a porta unica recebe. Um gesto novo do grupo entra AQUI e num ramo do dispatch, e
nao como uma quinta funcao publica — foi essa a licao do harness fiel: cada entrada extra e mais
um caminho que producao percorre e teste nao."""

StatusDaPorta = Literal["registrada", "duplicada", "grupo_nao_cadastrado", "delecao", "ignorado"]
"""Veredito de ROTEAMENTO. `delecao` e o unico que nao vem de uma mensagem: e o evento da
plataforma dizendo que uma mensagem morreu. `ignorado` e o gesto que a porta reconhece no tipo mas
ainda nao trata (reacao, edicao): entrou, nao escreveu nada, nao falou nada."""

MotivoSemVenda = Literal[
    "eco_do_agente",
    "nao_e_anuncio",
    "sem_valor",
    "varias_modelos",
    "nome_desconhecido",
    "nome_ambiguo",
    "venda_duplicada",
    "pergunta_de_pagamento",
    "pagamento_absorvido",
    "pagamento_coletivo",
    "pagamento_ambiguo",
    "pagamento_sem_venda_certa",
    "correcao_aplicada",
    "correcao_sem_efeito",
    "correcao_ambigua",
    "correcao_duplicada",
    "venda_anulada",
    "anulacao_ambigua",
    "delecao_sem_venda",
    "audio_sem_transcricao",
    "fechamento_postado",
    "cobranca_registrada",
    "cobranca_duplicada",
    "cobranca_anulada",
    "comprovante_conciliado",
    "comprovante_entrada_da_modelo",
    "comprovante_cliente_para_a_casa",
    "comprovante_de_cobranca",
    "comprovante_nao_classificado",
    "comprovante_ilegivel",
    "comprovante_duplicado",
    "comprovante_anulado",
    "imagem_sem_leitura",
    "nao_e_comprovante",
    "cadastro_atualizado",
    "cadastro_sem_efeito",
    "cadastro_de_terceiro",
    # --- Ficha de agendamento (ticket 06). Ficha NAO e venda: ela e o combinado, e por isso todo
    # motivo dela mora aqui, do lado de "o que a porta fez", e nunca em `vendas`.
    "ficha_registrada",
    "ficha_duplicada",
    "ficha_nome_desconhecido",
    "ficha_nome_ambiguo",
    "ficha_sem_modelo",
    "ficha_sem_conteudo",
    "comunicado_vinculado",
    "comunicado_ambiguo",
    # --- Grupo de fichas (ticket 19). A modelo nao vem do JID: ou o card a nomeia, ou nao ha
    # ficha. Os tres motivos abaixo sao de ROTEAMENTO por papel do grupo, e ficam aqui pelo mesmo
    # motivo dos outros: quem le o resultado quer saber por que aquela mensagem nao virou nada.
    "ficha_de_outra_modelo",
    "nao_e_ficha",
    "grupo_em_leitura",
    # --- Promocao da ficha a Venda registrada (ticket 07). A venda NASCE aqui, entao o motivo
    # de sucesso anda junto de `vendas`, e nao de `pagamentos`: nao houve pendencia de forma para
    # resolver — a forma chegou com o fato.
    "ficha_promovida",
    "ficha_ja_promovida",
    "promocao_ambigua",
    "promocao_sem_valor",
    # --- Vale dito no grupo (ticket 15). Vale nao e venda nem Cobranca da agencia: e dinheiro
    # EMPRESTADO a modelo, e por isso todo motivo dele tem prefixo proprio — quem investiga um
    # debito no extrato tem que conseguir separar, so pelo motivo, os dois eixos que debitam ela.
    "vale_registrado",
    "vale_duplicado",
    "vale_incompleto",
    "vale_corrigido",
    "vale_correcao_sem_efeito",
    "vale_correcao_duplicada",
    "vale_anulado",
    # --- Em que bolso o dinheiro caiu (ADR-0047, ticket 04). NAO e venda, nao e pagamento e nao e
    # correcao: e o campo que decide o SINAL do saldo dela, e por isso tem familia propria. Quem
    # investiga um extrato torto procura por aqui primeiro — `bolso_divergente` e o unico motivo
    # do modulo que significa "o agente viu duas evidencias brigando e nao escolheu sozinho".
    "bolso_fixado",
    "bolso_divergente",
]

# Ate onde a porta relê o grupo para se situar. 48 h cobre o vao real entre a pergunta e a
# resposta no export ("Foi pix ou din ?" 19:54 -> "Dinheiro" 20:00; anuncio de um dia respondido
# no outro) e serve so para LOCALIZAR a conversa: a venda que a resposta atinge pode ser de
# semanas atras (a fila de pendencia nao tem janela).
JANELA_DE_CONTEXTO = timedelta(hours=48)
MENSAGENS_DE_CONTEXTO = 40

# Prazo para uma resposta solta ("600") completar o anuncio incompleto que a antecedeu. Curto de
# proposito e MUITO menor que a janela de contexto: passado um dia, um numero solto no grupo tem
# muito mais chance de ser outra coisa (um valor de cobranca, um apartamento) do que a resposta
# atrasada de uma pergunta que ninguem lembra.
JANELA_DA_PERGUNTA_MINIMA = timedelta(hours=12)

# Teto de palavras para uma mensagem ser candidata a "resposta curta" (o "600", o "é a Duda").
# E a triagem que evita relê o grupo por causa de conversa: parágrafo nao responde pergunta
# minima. Barato de proposito — nao chama extracao, so conta palavras.
MAX_PALAVRAS_DA_RESPOSTA = 8

_PALAVRA = re.compile(r"\S+")

ExtratorDeAnuncio = Callable[[str], AnuncioDeVenda]
"""Leitura do anuncio. Injetavel: e ESTE o ponto de plugar um extrator de LLM quando a grafia do
grupo escapar do deterministico — e e o que o teste espiona para provar que mensagem social nao
custa extracao."""


class EnviarNoGrupo(Protocol):
    """Entrega de uma fala no grupo. A porta decide O QUE dizer; QUEM entrega (Evolution, teste,
    replay) e de fora — o modulo nunca fala com a rede por conta propria.

    `citar` e o **alvo do quote**, e ele e decisao da PORTA, nao do transporte. O recibo de uma
    venda cita o ANUNCIO, porque e no anuncio que a venda esta ancorada e e por ele que a correcao
    por quote (ticket 05) a encontra. Quando quem destravou o registro foi uma resposta posterior
    ("600", "é a Duda"), a mensagem que entrou NAO e o anuncio — deixar o transporte citar "a
    mensagem que acabou de chegar" faria o recibo convidar a uma correcao que nao acha venda
    nenhuma. `None` = citar a mensagem que entrou (o default do transporte), que e o certo para
    tudo que responde a propria mensagem: eco de correcao, pedido de reenvio, aviso de duplicata.
    """

    async def __call__(self, texto: str, *, citar: str | None = None) -> None: ...


@dataclass(frozen=True)
class ResultadoDaPorta:
    """O que a porta fez com a mensagem — o unico observavel do modulo para quem chama.

    Cresce por ADICAO nos tickets seguintes (correcoes, fechamento); o `status` continua sendo o
    veredito de ROTEAMENTO (a mensagem entrou?) e `motivo` o veredito de CONDUTA (o que a porta
    fez, ou por que nao fez nada).
    """

    status: StatusDaPorta
    grupo_id: UUID | None = None
    modelo_id: UUID | None = None
    mensagem_id: UUID | None = None
    vendas: tuple[UUID, ...] = field(default_factory=tuple)
    pagamentos: tuple[UUID, ...] = field(default_factory=tuple)
    """Vendas cuja Pendencia de forma de pagamento foi resolvida POR ESTA mensagem."""
    correcoes: tuple[UUID, ...] = field(default_factory=tuple)
    """Vendas que ESTA mensagem corrigiu (quote no recibo). Separado de `vendas` de proposito:
    quem soma receita quer o que NASCEU aqui; quem audita quer o que MUDOU."""
    anuladas: tuple[UUID, ...] = field(default_factory=tuple)
    """Vendas anuladas pela delecao da mensagem-fonte."""
    cobrancas: tuple[UUID, ...] = field(default_factory=tuple)
    """Cobrancas da agencia que ESTA mensagem registrou (ticket 08) — debito da modelo, nunca
    receita. Fora de `vendas` de proposito: quem soma dinheiro da casa nao pode encontrar isto no
    caminho."""
    cobrancas_quitadas: tuple[UUID, ...] = field(default_factory=tuple)
    """Cobrancas que o comprovante desta mensagem pagou. Espelha `abatidas` do outro eixo: uma diz
    que uma venda foi comprovada, esta diz que uma divida foi paga."""
    cobrancas_anuladas: tuple[UUID, ...] = field(default_factory=tuple)
    """Cobrancas PENDENTES anuladas pela delecao da mensagem-fonte. A ja quitada nao entra: apagar
    a mensagem nao desfaz um pagamento que tem comprovante amarrado."""
    vales: tuple[UUID, ...] = field(default_factory=tuple)
    """Vales que ESTA mensagem lancou (ticket 15) — adiantamento da casa a modelo, debito dela.

    Fora de `cobrancas` de proposito, e nao por preciosismo de nome: os dois debitam a modelo, mas
    so a cobranca espera comprovante (a rotina da manha cobra, o Pix quita). Somar os dois no
    mesmo campo faria a primeira leitura que confunde os eixos cobrar para sempre um adiantamento
    que nunca vai ter prova — e ninguem descobriria pelo saldo, que fecha igual."""
    vales_corrigidos: tuple[UUID, ...] = field(default_factory=tuple)
    """Vales que ESTA mensagem corrigiu (quote no recibo). Espelha `correcoes` do eixo da venda:
    quem soma debito quer o que NASCEU aqui; quem audita quer o que MUDOU."""
    vales_anulados: tuple[UUID, ...] = field(default_factory=tuple)
    """Vales anulados pela delecao da mensagem-fonte. So os que nasceram no GRUPO tem
    mensagem-fonte — o lancado pelo painel nao e alcancado por apagar fala nenhuma."""
    comprovante_id: UUID | None = None
    """O Comprovante de transferencia que ESTA mensagem trouxe — inclusive quando ele ficou
    retido (`nao_classificado`) ou ilegivel. Retido tambem e resultado: e dinheiro que saiu."""
    abatidas: tuple[UUID, ...] = field(default_factory=tuple)
    """Vendas que o comprovante desta mensagem fechou (FIFO). Separado de `pagamentos`: aquele diz
    COMO a venda foi paga, este diz que o dinheiro chegou e esta comprovado."""
    bolsos: tuple[UUID, ...] = field(default_factory=tuple)
    """Vendas cujo BOLSO esta mensagem fixou (ADR-0047, ticket 04) — em que conta o dinheiro
    daquele atendimento caiu.

    Fora de `correcoes` de proposito, ainda que o rastro no banco seja um evento de correcao: quem
    audita uma correcao procura um numero que mudou (valor, cliente, forma), e o bolso nao muda
    numero nenhum — ele inverte o SINAL do saldo. A venda de R$ 1.200,00 com bolso `dela` e ela
    devendo; com bolso `empresa` e a casa devendo a comissao. Somar os dois campos faria a unica
    escrita capaz de virar o extrato do avesso desaparecer no meio do retrabalho de digitacao."""
    pendencias: tuple[Pendencia, ...] = field(default_factory=tuple)
    """Pendencias vivas das vendas que esta mensagem tocou. Nunca travam nada — sao o que a
    rotina da manha (ticket 10) vai cobrar e o que o painel (11) mostra."""
    cadastro: DadoCadastralRegistrado | None = None
    """O Dado cadastral que ESTA mensagem ensinou (ticket 12) — sempre com `resposta=None`. Fica
    no resultado por ser efeito observavel: o unico jeito de provar que o agente aprendeu calado e
    ver o que ele aprendeu sem ter falado."""
    extrato: Extrato | None = None
    """O Fechamento que ESTA mensagem pediu (ticket 09). Preenchido so no pedido: e o retrato do
    aberto da modelo, nao um acompanhamento que sai em toda mensagem — recalcula-lo a cada linha
    do grupo seria pagar duas consultas por sticker."""
    resposta: str | None = None
    motivo: MotivoSemVenda | None = None
    ficha_id: UUID | None = None
    """A Ficha de agendamento que ESTA mensagem criou — ou aquela que ela reconheceu (o repost que
    caiu no dedup, o comunicado que vinculou). Fica fora de `vendas` de proposito: ficha e o
    COMBINADO, nao receita, e quem soma dinheiro nao pode encontra-la no caminho (ADR-0044 §2)."""


async def processar_evento_do_grupo(
    conn: AsyncConnection[Any],
    evento: EventoDoGrupo,
    *,
    extrair: ExtratorDeAnuncio = extrair_anuncio,
    enviar: EnviarNoGrupo | None = None,
    transcrever: TranscreverAudio | None = None,
    ler_comprovante: LerComprovante | None = None,
    ler_intencao: LerIntencao | None = None,
) -> ResultadoDaPorta:
    """A PORTA UNICA: um evento do Grupo financeiro entra, os efeitos saem.

    Recebe a uniao (`EventoDoGrupo`) e roteia por tipo — mensagem segue o fluxo completo (registro,
    audio, imagem, conduta); delecao anula o que nasceu da mensagem morta; reacao e edicao caem no
    ramo que ignora com log, porque existem no tipo e ainda nao tem comportamento. Todos devolvem o
    MESMO `ResultadoDaPorta` e recebem as MESMAS dependencias injetadas: quem chama nao precisa
    saber qual ramo rodou.

    As dependencias que um ramo nao usa sao aceitas e ignoradas de proposito. E o que mantem a
    costura UNICA: o webhook passa o ouvido, o olho e a boca uma vez so, para qualquer evento, e um
    gesto que amanha precisar falar no grupo nao muda a assinatura de ninguem.

    Nao levanta por evento indesejado: grupo desconhecido nao e erro, e o caso NORMAL do numero
    compartilhado da ProceX (myEYE e os grupos financeiros dividem o mesmo WhatsApp). Erro seria
    responder.
    """
    if isinstance(evento, MensagemDoGrupo):
        resultado = await _processar_mensagem(
            conn,
            evento,
            extrair=extrair,
            enviar=enviar,
            transcrever=transcrever,
            ler_comprovante=ler_comprovante,
            ler_intencao=ler_intencao,
        )
        await _registrar_a_propria_fala(conn, resultado, msg=evento, enviar=enviar)
        return resultado
    if isinstance(evento, DelecaoNoGrupo):
        return await _processar_delecao(conn, evento)
    return _ignorar_gesto(evento)


def _ignorar_gesto(evento: ReacaoNoGrupo | EdicaoNoGrupo) -> ResultadoDaPorta:
    """Gesto que a porta conhece no tipo e ainda nao trata: sai com log, sem tocar no banco.

    Espelho do ramo de grupo nao cadastrado — ignorar em silencio observavel e o default seguro do
    modulo. Nao consulta `grupos_financeiros` de proposito: nao havendo o que fazer com o gesto,
    saber de quem ele e nao muda nada e custaria uma ida ao banco por reacao de grupo alheio (o
    numero e compartilhado). Pelo mesmo motivo do outro ramo, o log NAO leva o `autor_jid`: ele e
    o telefone E.164 de quem reagiu, e este caminho dispara para grupo que nem e nosso.
    """
    _logger.info(
        "grupo_financeiro_gesto_ignorado gesto=%s jid=%s message_id=%s",
        "reacao" if isinstance(evento, ReacaoNoGrupo) else "edicao",
        evento.grupo_jid,
        evento.evolution_message_id,
    )
    return ResultadoDaPorta(status="ignorado")


async def processar_mensagem_do_grupo(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    extrair: ExtratorDeAnuncio = extrair_anuncio,
    enviar: EnviarNoGrupo | None = None,
    transcrever: TranscreverAudio | None = None,
    ler_comprovante: LerComprovante | None = None,
    ler_intencao: LerIntencao | None = None,
) -> ResultadoDaPorta:
    """Wrapper fino sobre `processar_evento_do_grupo` — a entrada de mensagem de sempre.

    Continua valendo (webhook, replay do export, testes) e continua sendo a mesma execucao: uma
    mensagem E um evento do grupo. Mantido para que a generalizacao da porta nao mexa em nenhum
    chamador.
    """
    return await processar_evento_do_grupo(
        conn,
        msg,
        extrair=extrair,
        enviar=enviar,
        transcrever=transcrever,
        ler_comprovante=ler_comprovante,
        ler_intencao=ler_intencao,
    )


async def _processar_mensagem(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    extrair: ExtratorDeAnuncio = extrair_anuncio,
    enviar: EnviarNoGrupo | None = None,
    transcrever: TranscreverAudio | None = None,
    ler_comprovante: LerComprovante | None = None,
    ler_intencao: LerIntencao | None = None,
) -> ResultadoDaPorta:
    """O ramo de MENSAGEM da porta unica: recebe uma mensagem e devolve o que foi feito com ela.

    Nao levanta por mensagem indesejada: grupo desconhecido nao e erro, e o caso NORMAL do numero
    compartilhado da ProceX (myEYE e os grupos financeiros dividem o mesmo WhatsApp). Erro seria
    responder.

    `transcrever` (ticket 06) e `ler_comprovante` (07) sao o ouvido e o olho do agente, injetados
    como todo o resto que sai do processo: o teste stuba a ida ao provider e exercita a MESMA
    conduta que a producao roda com o audio e a imagem reais — e sem eles (ambiente sem provider)
    o agente segue funcionando surdo e cego, so registrando a mensagem.
    """
    grupo = await buscar_grupo_cadastrado_por_jid(conn, msg.grupo_jid)
    if grupo is None:
        GRUPO_FINANCEIRO.labels("grupo_nao_cadastrado").inc()
        # SEM o `autor_jid` aqui, de proposito: ele e o telefone E.164 de quem falou, e este ramo
        # dispara para TODO grupo que nao e Grupo financeiro — o numero e compartilhado, e a
        # modelo opera no numero pessoal dela, que vive em grupo de familia e de amigas. Logar o
        # autor transformaria um log de roteamento num acumulador de telefone de terceiro. O JID
        # do grupo basta para diagnosticar "por que este grupo nao entrou".
        _logger.info(
            "grupo_financeiro_nao_cadastrado jid=%s message_id=%s",
            msg.grupo_jid,
            msg.evolution_message_id,
        )
        return ResultadoDaPorta(status="grupo_nao_cadastrado")

    if isinstance(grupo, GrupoSemDona):
        return await _processar_no_grupo_sem_dona(conn, msg, grupo=grupo, enviar=enviar)

    mensagem_id = await registrar_mensagem(conn, grupo.id, msg)
    if mensagem_id is None:
        # Entrega duplicada do router (medida em 1-56 ms de diferenca no myEYE) ou retry da
        # Evolution. A mensagem ja esta registrada: parar aqui e o que impede o processamento
        # duplo de tudo que os proximos tickets penduram nesta porta.
        GRUPO_FINANCEIRO.labels("duplicada").inc()
        _logger.info(
            "grupo_financeiro_mensagem_duplicada jid=%s chave=%s",
            msg.grupo_jid,
            msg.chave_dedup(),
        )
        return ResultadoDaPorta(status="duplicada", grupo_id=grupo.id, modelo_id=grupo.modelo_id)

    GRUPO_FINANCEIRO.labels("registrada").inc()
    base = ResultadoDaPorta(
        status="registrada",
        grupo_id=grupo.id,
        modelo_id=grupo.modelo_id,
        mensagem_id=mensagem_id,
    )

    if msg.tipo == "audio" and not msg.de_mim:
        # DEPOIS do roteamento e do dedup, e so para audio de OUTRA pessoa: transcrever antes seria
        # pagar STT por mensagem de grupo alheio (o numero e compartilhado com o myEYE), pela
        # segunda entrega do router e pelo eco do proprio agente. Esta ordem e a diferenca entre
        # ouvir o grupo e transcrever a internet inteira.
        ouvida = await _ouvir(conn, msg, mensagem_id=mensagem_id, transcrever=transcrever)
        if ouvida is None:
            return _sem_venda(base, "audio_sem_transcricao")
        msg = ouvida

    if msg.tipo == "imagem" and not msg.de_mim:
        # Mesma ordem e mesmo motivo do audio: OCR e caro e so vale para imagem de gente, uma vez
        # por mensagem.
        lido = await _ler_comprovante(
            conn, msg, grupo=grupo, base=base, ler=ler_comprovante, enviar=enviar
        )
        if lido.comprovante_id is not None or not (msg.caption or "").strip():
            return lido
        # A foto nao rendeu comprovante (nao era um, ou nao deu para ler) mas veio com LEGENDA:
        # legenda e texto que um humano escreveu, e ela segue para as leituras de sempre. Sem
        # isso, um anuncio postado como legenda de foto — que antes deste ticket virava venda —
        # passaria a ser engolido pelo caminho da imagem.

    return await _conduzir(
        conn, msg, grupo=grupo, base=base, extrair=extrair, enviar=enviar, ler_intencao=ler_intencao
    )


# --- grupo sem dona: o Grupo de fichas e o caixa dos telefonistas (ticket 19) --------------------
#
# A reuniao de 20/08 abriu a possibilidade de a ficha COMPLETA ser postada num grupo dedicado so
# dos telefonistas, com o Comunicado indo ao grupo individual da modelo (ADR-0046 §2). O arranjo
# nao esta decidido — "a gente pode testar" —, e e exatamente por isso que o codigo nao pode
# assumir que o card caiu no grupo de quem vai pagar: aqui a modelo vem do campo `Nome da modelo`
# pelo resolver closed-world, e um grupo sem card e um grupo sem nada.


async def _processar_no_grupo_sem_dona(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoSemDona,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """O ramo dos grupos que NAO pertencem a uma modelo. So a ficha entra; o resto e log.

    Nenhuma leitura de dinheiro roda aqui, e nao por economia: venda, pagamento, comprovante,
    cobranca, vale, fechamento e dado cadastral sao todos **da dona do grupo**, e num grupo sem
    dona cada um deles teria que escolher uma modelo por conta propria. O card e o unico documento
    que diz de quem ele e.

    **Calado como sempre foi** ao receber uma ficha (ADR-0044 §1): sem recibo, sem eco. A unica
    fala possivel e a pergunta minima por um nome que o cadastro nao conhece — e ela e postada
    AQUI, no grupo de quem escreveu o nome, que e quem sabe responder.

    O caixa dos telefonistas entra so em LEITURA (spec 0006, ticket 17): a mensagem e registrada e
    nada mais acontece — nem venda, nem ficha, nem comprovante, nem fala. E este `return` que
    impede a mesma venda de entrar duas vezes, pelo grupo individual e pelo caixa; a conferencia
    entre as duas fontes e derivada depois, na leitura
    (`dominio/grupo_financeiro/conferencia.py`, `service.conferencia_do_caixa`), e nunca escreve.
    """
    mensagem_id = await registrar_mensagem(conn, grupo.id, msg)
    if mensagem_id is None:
        GRUPO_FINANCEIRO.labels("duplicada").inc()
        return ResultadoDaPorta(status="duplicada", grupo_id=grupo.id)

    GRUPO_FINANCEIRO.labels("registrada").inc()
    base = ResultadoDaPorta(status="registrada", grupo_id=grupo.id, mensagem_id=mensagem_id)

    if grupo.papel == "caixa_telefonistas":
        return _sem_venda(base, "grupo_em_leitura")

    texto = msg.texto or msg.caption or ""
    if msg.de_mim or e_fala_do_agente(texto):
        # A propria pergunta do agente voltando pelo webhook. Sem este corte ela seria relida como
        # texto do grupo a cada entrega — o mesmo motivo do corte no ramo da modelo.
        return _sem_venda(base, "eco_do_agente")

    # Audio e imagem nao sao ouvidos nem lidos neste grupo, de proposito: o que ele existe para
    # receber e um formulario DIGITADO. Pagar STT/OCR aqui seria transcrever a conversa dos
    # telefonistas para nao poder fazer nada com ela — no grupo sem dona nao ha venda para
    # comprovar nem pendencia para fechar.
    ficha = await _registrar_ficha_se_for_card(
        conn,
        msg,
        grupo_id=grupo.id,
        dona_do_grupo=None,
        base=base,
        texto=texto,
        enviar=enviar,
    )
    if ficha is not None:
        return ficha

    # Conversa entre telefonistas ("subiu?", "ela chegou"). Fica no log de origem e mais nada.
    return _sem_venda(base, "nao_e_ficha")


async def processar_delecao_do_grupo(
    conn: AsyncConnection[Any], delecao: DelecaoNoGrupo
) -> ResultadoDaPorta:
    """Wrapper fino sobre `processar_evento_do_grupo` — a entrada de delecao de sempre.

    Mesma execucao do ramo de delecao da porta unica; existe para nao mexer em chamador nenhum.
    """
    return await processar_evento_do_grupo(conn, delecao)


async def _processar_delecao(
    conn: AsyncConnection[Any], delecao: DelecaoNoGrupo
) -> ResultadoDaPorta:
    """O ramo de DELECAO: a plataforma avisou que uma mensagem foi apagada, e o que nasceu dela
    deixa de valer.

    Apagar e repostar e como o grupo corrige hoje (08/08: "Mensagem apagada" seguida do anuncio de
    novo). Aqui a anulacao e IMEDIATA e sem janela de trava — espelho de "Registro de resultado e
    efetivo imediatamente, Fernando corrige depois no painel": quem apagou sabe o que apagou, e
    segurar a venda esperando um repost que talvez nao venha deixaria no extrato um numero que
    ninguem mais reconhece.

    **O agente nao fala.** A delecao e um gesto deliberado de quem estava olhando para a mensagem;
    o "🗑️ anulei" seguido do "✅ Registrei" do repost dobraria o ruido do gesto mais comum do
    grupo. O rastro fica onde rastro deve ficar: no evento de auditoria e no painel.

    Nao levanta por delecao que nao conhecemos (mensagem social, mensagem anterior ao modulo,
    grupo de outra pessoa) — o numero da ProceX e compartilhado e delecao alheia e o caso normal.
    """
    grupo = await buscar_grupo_cadastrado_por_jid(conn, delecao.grupo_jid)
    if grupo is None:
        GRUPO_FINANCEIRO.labels("grupo_nao_cadastrado").inc()
        return ResultadoDaPorta(status="grupo_nao_cadastrado")

    if isinstance(grupo, GrupoSemDona):
        # Grupo de fichas ou caixa: nada de dinheiro nasceu la, entao nao ha o que anular. A
        # mensagem e marcada apagada assim mesmo — o log de origem tem que continuar refletindo o
        # que se ve no WhatsApp, senao o card apagado ficaria de pe no contexto que a porta relê.
        # Apagar o card NAO cancela a ficha: quem move o estado dela e o ❌/"nao veio", com
        # rastro em `ficha_de_agendamento_eventos`.
        GRUPO_FINANCEIRO.labels("delecao").inc()
        await marcar_mensagem_apagada(
            conn, grupo.id, delecao.evolution_message_id, em=delecao.ocorrida_em
        )
        return _sem_venda(
            ResultadoDaPorta(status="delecao", grupo_id=grupo.id), "delecao_sem_venda"
        )

    GRUPO_FINANCEIRO.labels("delecao").inc()
    base = ResultadoDaPorta(status="delecao", grupo_id=grupo.id, modelo_id=grupo.modelo_id)
    mensagem_id = await marcar_mensagem_apagada(
        conn, grupo.id, delecao.evolution_message_id, em=delecao.ocorrida_em
    )
    if mensagem_id is None:
        return _sem_venda(base, "delecao_sem_venda")

    anuladas: list[VendaRegistrada] = []
    for venda in await vendas_da_mensagem(conn, mensagem_id):
        anulada = await anular_venda(conn, venda.id)
        if anulada is None:  # pragma: no cover - reentrega concorrente do mesmo evento
            continue
        await registrar_eventos_da_venda(conn, anulada.id, tipo="anulacao", mensagem_id=mensagem_id)
        anuladas.append(anulada)

    # A Cobranca da agencia (ticket 08) morre pelo mesmo gesto e no mesmo lugar: apagar a mensagem
    # do "*3RJ Suporte/Anuncio:* R$ 385,80" tira o debito da modelo. So a PENDENTE — o repo nao
    # devolve a que ja tem comprovante amarrado, porque apagar mensagem nao desfaz pagamento.
    # O Comprovante de transferencia (ticket 07) morre pelo mesmo gesto: a foto errada (o Pix de
    # outra pessoa, o valor trocado) e apagada, e o abate que ela produziu tem que voltar atras.
    # Sem isto a venda seguia marcada como paga por uma prova que nao existe mais no grupo — e,
    # como o extrato continuava fechando, ninguem ia procurar.
    comprovantes_anulados, soltas = await anular_comprovantes_da_mensagem(conn, mensagem_id)
    for comprovante in comprovantes_anulados:
        GRUPO_FINANCEIRO_COMPROVANTES.labels("anulado").inc()
        _logger.info(
            "grupo_financeiro_comprovante_anulado comprovante_id=%s grupo_id=%s valor=%s "
            "vendas_soltas=%s",
            comprovante.id,
            grupo.id,
            comprovante.valor,
            len(soltas),
        )
    for venda in soltas:
        await registrar_eventos_da_venda(
            conn, venda.id, tipo="abate_desfeito", mensagem_id=mensagem_id
        )

    # O Vale (ticket 15) morre pelo mesmo gesto: apagar "adiantei 500 pra ela" tira o debito do
    # saldo dela. Alcanca SO o que nasceu no grupo — o lancado no painel nao tem `mensagem_id`, e
    # apagar uma fala no WhatsApp nao pode desfazer o que o gestor digitou na tela.
    vales_anulados = await anular_lancamentos_manuais_da_mensagem(conn, mensagem_id)
    for vale in vales_anulados:
        GRUPO_FINANCEIRO_ANUNCIOS.labels("vale_anulado").inc()
        _logger.info(
            "grupo_financeiro_vale_anulado vale_id=%s modelo_id=%s valor=%s mensagem_id=%s",
            vale.id,
            vale.modelo_id,
            vale.valor,
            mensagem_id,
        )

    cobrancas_anuladas = await anular_cobrancas_da_mensagem(conn, mensagem_id)
    for cobranca in cobrancas_anuladas:
        GRUPO_FINANCEIRO_ANUNCIOS.labels("cobranca_anulada").inc()
        _logger.info(
            "grupo_financeiro_cobranca_anulada cobranca_id=%s modelo_id=%s valor=%s mensagem_id=%s",
            cobranca.id,
            cobranca.modelo_id,
            cobranca.valor,
            mensagem_id,
        )

    if not anuladas:
        if vales_anulados and not cobrancas_anuladas and not comprovantes_anulados:
            # Apagaram a fala do adiantamento e mais nada. "delecao_sem_venda" seria verdade e
            # esconderia o unico efeito que houve — um debito saiu do saldo dela.
            return ResultadoDaPorta(
                status="delecao",
                grupo_id=grupo.id,
                modelo_id=grupo.modelo_id,
                mensagem_id=mensagem_id,
                vales_anulados=tuple(v.id for v in vales_anulados),
                motivo="vale_anulado",
            )
        if cobrancas_anuladas:
            return ResultadoDaPorta(
                status="delecao",
                grupo_id=grupo.id,
                modelo_id=grupo.modelo_id,
                mensagem_id=mensagem_id,
                cobrancas_anuladas=tuple(c.id for c in cobrancas_anuladas),
                vales_anulados=tuple(v.id for v in vales_anulados),
                motivo="cobranca_anulada",
            )
        if comprovantes_anulados:
            # Apagaram a FOTO, nao o anuncio: nenhuma venda morreu, mas as que ele fechava
            # voltaram para a fila. O motivo precisa dizer isso — "delecao_sem_venda" e verdade e
            # esconde o unico efeito que houve.
            return ResultadoDaPorta(
                status="delecao",
                grupo_id=grupo.id,
                modelo_id=grupo.modelo_id,
                mensagem_id=mensagem_id,
                comprovante_id=comprovantes_anulados[0].id,
                pendencias=tuple(p for venda in soltas for p in pendencias_da_venda(venda)),
                motivo="comprovante_anulado",
            )
        # Mensagem conhecida que nunca virou venda (conversa, o proprio recibo) ou delecao
        # reentregue. O carimbo de apagada ja tirou a mensagem do contexto, que e o efeito que
        # importa quando o que morreu foi um anuncio incompleto.
        return _sem_venda(base, "delecao_sem_venda")

    for venda in anuladas:
        GRUPO_FINANCEIRO_ANUNCIOS.labels("venda_anulada").inc()
        _logger.info(
            "grupo_financeiro_venda_anulada venda_id=%s modelo_id=%s valor=%s mensagem_id=%s",
            venda.id,
            venda.modelo_id,
            venda.valor,
            mensagem_id,
        )
    return ResultadoDaPorta(
        status="delecao",
        grupo_id=grupo.id,
        modelo_id=anuladas[0].modelo_id if len(anuladas) == 1 else grupo.modelo_id,
        mensagem_id=mensagem_id,
        anuladas=tuple(venda.id for venda in anuladas),
        cobrancas_anuladas=tuple(c.id for c in cobrancas_anuladas),
        vales_anulados=tuple(v.id for v in vales_anulados),
        motivo="venda_anulada",
    )


async def _conduzir(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    extrair: ExtratorDeAnuncio,
    enviar: EnviarNoGrupo | None,
    ler_intencao: LerIntencao | None = None,
) -> ResultadoDaPorta:
    """Da mensagem ja registrada ate o efeito — venda, correcao, pergunta, pagamento ou silencio."""
    texto = msg.texto or msg.caption or ""

    if msg.de_mim or e_fala_do_agente(texto):
        # Eco do proprio numero da ProceX (a EvoGo assina SEND_MESSAGE). Sem este corte o recibo
        # "✅ Registrei: … R$ 700,00 …" voltaria pela porta e o agente registraria a si mesmo.
        #
        # A segunda metade (`e_fala_do_agente`) e defesa em profundidade contra o quirk do
        # `fromMe`: ele e relativo a INSTANCIA que entregou, e a modelo e participante do grupo
        # com uma instancia propria apontando para este webhook — na entrega dela o sinal se
        # inverte. O filtro de instancia do webhook resolve isso, mas e fail-open enquanto
        # `GRUPO_FINANCEIRO_INSTANCIA` nao esta configurada (ver `voz.py`).
        return _sem_venda(base, "eco_do_agente")

    # A correcao vem ANTES da leitura de anuncio porque ela e a unica que sabe de qual venda esta
    # falando: o quote aponta a venda, entao "foi 650" ali nao e um valor solto a espera de um
    # anuncio incompleto, e "o cliente era Ramon" nao e um anuncio novo. Sem quote, nada disso e
    # correcao — as mesmas palavras seguem para as leituras de sempre.
    corrigida = await _corrigir_por_quote(conn, msg, grupo=grupo, base=base, enviar=enviar)
    if corrigida is not None:
        return corrigida

    # O Vale (ticket 15) tem a MESMA porta de correcao, e ela vem logo aqui pelo mesmo motivo da
    # venda: o quote e o unico sinal que diz de qual lancamento se fala. "foi 600" respondendo o
    # recibo do vale nao e um valor solto a espera de anuncio incompleto — e a correcao de um
    # debito que ja esta no saldo dela. Depois da venda porque venda vence: um quote que acha as
    # duas coisas nao existe (recibos diferentes, mensagens-fonte diferentes), mas a ordem torna
    # isso explicito em vez de acidental.
    vale_corrigido = await _corrigir_vale_por_quote(
        conn, msg, grupo=grupo, base=base, texto=texto, enviar=enviar
    )
    if vale_corrigido is not None:
        return vale_corrigido

    # O pedido de fechamento vem DEPOIS da correcao (quem cita um recibo esta falando daquela
    # venda, nao pedindo extrato) e ANTES de tudo que le valor: "fechamento" nao e anuncio, nao e
    # forma de pagamento e nao e resposta de pergunta minima — deixa-lo cair na cascata faria uma
    # palavra de comando disputar leitura com o dinheiro do grupo.
    if e_pedido_de_fechamento(texto):
        return await _fechar(conn, grupo=grupo, base=base, enviar=enviar)

    # A Ficha do telefonista vem ANTES do leitor de anuncio e tem precedencia sobre ele: o card e
    # um formulario que a propria casa distribuiu, e ler "Cliente: Igor / Valor total: R$ 700" como
    # anuncio de venda registraria como receita um atendimento que ainda nao aconteceu. Nao casando
    # nenhum dos tres documentos, a mensagem segue exatamente por onde seguia — o telefonista vai
    # esquecer o card, e o sistema nao pode ficar mudo quando ele escrever solto.
    ficha = await _registrar_ficha_se_for_card(
        conn,
        msg,
        grupo_id=grupo.id,
        dona_do_grupo=grupo.modelo_id,
        base=base,
        texto=texto,
        enviar=enviar,
    )
    if ficha is not None:
        return ficha

    if parece_anuncio_de_venda(texto):
        return await _lancar_venda_se_for_anuncio(
            conn, msg, grupo=grupo, base=base, extrair=extrair, enviar=enviar
        )

    # A Cobranca da agencia vem DEPOIS do anuncio e ANTES das leituras soltas. Depois do anuncio
    # porque venda vence sempre: uma mensagem com a gramatica do anuncio e venda, mesmo que fale
    # em site ou anuncio. Antes das leituras soltas porque a cobranca tem cifra dentro, e todo
    # leitor dali para baixo procura numero — o R$ 385,80 nao pode virar o valor de um anuncio
    # incompleto que esperava resposta.
    cobranca = await _registrar_cobranca(
        conn, msg, grupo=grupo, base=base, texto=texto, enviar=enviar
    )
    if cobranca is not None:
        return cobranca

    # O Vale vem DEPOIS da cobranca e ANTES das leituras soltas, e as duas vizinhancas sao
    # deliberadas. Depois da cobranca porque as allowlists sao disjuntas e a ordem nao decide
    # nada, mas deixa escrito qual dos dois eixos de debito e lido primeiro. Antes das leituras
    # soltas pelo motivo de sempre: "adiantei 500 pra ela" tem cifra dentro, e todo leitor dali
    # para baixo procura numero — o 500 de um adiantamento nao pode virar o valor de um anuncio
    # incompleto que esperava resposta.
    vale = await _registrar_vale(conn, msg, grupo=grupo, base=base, texto=texto, enviar=enviar)
    if vale is not None:
        return vale

    # O bolso vem DEPOIS de tudo que le cifra e ANTES das leituras soltas, e as duas vizinhancas
    # sao deliberadas. Depois porque "ficou com voce" nao tem numero dentro e nunca disputa com
    # anuncio, cobranca ou vale — mas escrever a ordem deixa isso verificavel em vez de
    # acidental. Antes de `_absorver_resposta` por causa do teto de palavras dela (8, contra as 12
    # que a fala de bolso admite) e porque o alvo e outro: la se responde a forma de pagamento de
    # uma venda aberta, aqui se afirma em que conta o dinheiro de uma venda ja registrada caiu.
    bolso = await _absorver_bolso(conn, msg, grupo=grupo, base=base, texto=texto, enviar=enviar)
    if bolso is not None:
        return bolso

    return await _absorver_resposta(
        conn,
        msg,
        grupo=grupo,
        base=base,
        texto=texto,
        extrair=extrair,
        enviar=enviar,
        ler_intencao=ler_intencao,
    )


# --- audio: ouvir e seguir como se fosse texto --------------------------------------------------


async def _ouvir(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    mensagem_id: UUID,
    transcrever: TranscreverAudio | None,
) -> MensagemDoGrupo | None:
    """Transcreve o audio e devolve a mensagem com o texto dela. `None` = nao deu para ouvir.

    O texto transcrito vai para o LOG DE ORIGEM (a mesma coluna do texto digitado) antes de
    qualquer conduta. Sem isso o audio ficaria mudo no contexto: o "600" falado destravaria o
    anuncio agora, mas a proxima mensagem releria o grupo e veria uma linha vazia no lugar da
    resposta — e o mesmo buraco faria um anuncio DITADO nunca poder ser completado depois.

    Falhar aqui nao e excecao: audio ruim, provider fora e chave ausente sao os tres casos comuns,
    e nenhum deles pode derrubar o turno ou fazer a Evolution reentregar a mensagem em loop (o
    webhook e sincrono — levantar aqui viraria retry infinito). Fica o carimbo no log, a metrica e
    a pendencia aberta, que e quem cobra de novo na rotina da manha.
    """
    if msg.audio is None or transcrever is None:
        # Sem bytes (MinIO fora, download barrado) ou sem provider (`OPENROUTER_API_KEY` vazio num
        # redeploy — ja aconteceu com o OCR do Pix). Distinguido do erro de proposito: um e
        # infraestrutura desta casa, o outro e o dia ruim do provider.
        resultado = "sem_audio" if msg.audio is None else "sem_transcritor"
        GRUPO_FINANCEIRO_AUDIO.labels(resultado).inc()
        _logger.warning(
            "grupo_financeiro_audio_nao_ouvido motivo=%s mensagem_id=%s", resultado, mensagem_id
        )
        await gravar_texto_da_mensagem(conn, mensagem_id, AUDIO_SEM_TRANSCRICAO)
        return None

    try:
        ouvido = await transcrever(msg.audio)
    except Exception:
        # Provider fora, timeout, 4xx de payload. Rotulado a parte do audio mudo porque as duas
        # causas pedem coisas diferentes de quem olha o painel: uma e nossa, a outra e da fila.
        GRUPO_FINANCEIRO_AUDIO.labels("erro").inc()
        _logger.warning("grupo_financeiro_audio_erro mensagem_id=%s", mensagem_id, exc_info=True)
        await gravar_texto_da_mensagem(conn, mensagem_id, AUDIO_SEM_TRANSCRICAO)
        return None

    texto = (ouvido or "").strip()
    if not texto:
        # Audio sem fala ou recusa do modelo. O agente NAO responde "nao entendi": ele e ingestor
        # silencioso, e a modelo que mandou um audio social receberia um pedido de repeticao sobre
        # uma mensagem que nunca foi para ele. Quando o audio ERA necessario, quem volta a cobrar
        # e a pendencia, que continua aberta.
        GRUPO_FINANCEIRO_AUDIO.labels("vazio").inc()
        await gravar_texto_da_mensagem(conn, mensagem_id, AUDIO_SEM_TRANSCRICAO)
        return None

    GRUPO_FINANCEIRO_AUDIO.labels("ok").inc()
    _logger.info(
        "grupo_financeiro_audio_transcrito mensagem_id=%s chars=%d", mensagem_id, len(texto)
    )
    await gravar_texto_da_mensagem(conn, mensagem_id, texto)
    # A partir daqui a mensagem E texto: nenhum passo adiante pergunta se ela veio falada, que e
    # o que garante que "foi pix" dito no audio faca exatamente o que faria digitado.
    return replace(msg, texto=texto)


# --- imagem: o Comprovante de transferencia -----------------------------------------------------


async def _ler_comprovante(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    ler: LerComprovante | None,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """Le a imagem, classifica o comprovante e abate as vendas pix abertas (FIFO).

    Tres desfechos e tres condutas, e a diferenca entre eles e o que separa um agente util de um
    que enche o grupo:

    * **abateu** -> confirmacao curta com o que ainda falta comprovar;
    * **nao casou com venda nenhuma** -> o comprovante fica RETIDO (`nao_classificado`) e sai UMA
      pergunta. E o caso real do R$ 385,80 (pagamento da Cobranca da agencia, ticket 08);
    * **ilegivel** -> pede reenvio, uma vez, como o myEYE faz.

    Foto que nao e comprovante (o print do site de 06/08) morre calada: o agente nao comenta
    imagem. E falha NOSSA — provider fora, chave que sumiu no redeploy — tambem morre calada, e
    nao vira pedido de reenvio: mandar a modelo reenviar a foto enquanto o OpenRouter esta fora
    e um loop que ela paga com paciencia e a casa nao ganha nada.
    """
    if msg.imagem is None or ler is None:
        resultado = "sem_imagem" if msg.imagem is None else "sem_leitor"
        GRUPO_FINANCEIRO_COMPROVANTES.labels(resultado).inc()
        _logger.warning(
            "grupo_financeiro_comprovante_nao_lido motivo=%s mensagem_id=%s",
            resultado,
            base.mensagem_id,
        )
        return _sem_venda(base, "imagem_sem_leitura")

    try:
        leitura = await ler(msg.imagem)
    except Exception:
        # O webhook e sincrono: levantar aqui viraria reentrega em loop da Evolution — a mesma
        # imagem, o mesmo OCR, o mesmo custo, para sempre.
        GRUPO_FINANCEIRO_COMPROVANTES.labels("erro").inc()
        _logger.warning(
            "grupo_financeiro_comprovante_erro mensagem_id=%s", base.mensagem_id, exc_info=True
        )
        return _sem_venda(base, "imagem_sem_leitura")

    if leitura is None:
        GRUPO_FINANCEIRO_COMPROVANTES.labels("erro").inc()
        return _sem_venda(base, "imagem_sem_leitura")
    if not leitura.e_comprovante:
        GRUPO_FINANCEIRO_COMPROVANTES.labels("nao_e_comprovante").inc()
        return _sem_venda(base, "nao_e_comprovante")

    if not leitura.legivel or leitura.valor is None or leitura.valor <= 0:
        return await _pedir_reenvio(conn, grupo=grupo, base=base, leitura=leitura, enviar=enviar)

    return await _conciliar_comprovante(
        conn,
        grupo=grupo,
        base=base,
        leitura=leitura,
        valor=leitura.valor,
        dia=msg.dia_brt(),
        recebida_em=msg.recebida_em,
        conteudo_hash=_hash_da_imagem(msg.imagem),
        enviar=enviar,
    )


def _hash_da_imagem(imagem: ImagemDoGrupo) -> str:
    """A identidade da FOTO — o que o dedup de conteudo do comprovante usa.

    sha256 dos bytes: a mesma imagem reenviada (ou encaminhada) tem os mesmos bytes, e dois Pix
    diferentes do mesmo valor no mesmo dia nao tem. Nao guardamos a imagem, so este resumo.
    """
    return hashlib.sha256(imagem.conteudo).hexdigest()


async def _comprovante_repetido(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    conteudo_hash: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """A foto ja tinha virado comprovante neste grupo: diz o que ja foi contado e para por aqui."""
    GRUPO_FINANCEIRO_COMPROVANTES.labels("duplicado").inc()
    anterior = await comprovante_por_conteudo(conn, grupo.id, conteudo_hash)
    _logger.info(
        "grupo_financeiro_comprovante_duplicado grupo_id=%s mensagem_id=%s anterior=%s",
        grupo.id,
        base.mensagem_id,
        None if anterior is None else anterior.id,
    )
    if anterior is None:
        # Reentrega da MESMA mensagem (o outro gate, por `mensagem_id`): o grupo nao mandou nada
        # de novo, entao nao ha o que responder.
        return _sem_venda(base, "comprovante_duplicado")
    aviso = montar_aviso_de_comprovante_repetido(anterior)
    await _postar(enviar, aviso)
    return _sem_venda(base, "comprovante_duplicado", resposta=aviso)


async def _pedir_reenvio(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    leitura: LeituraDoComprovante,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """Comprovante que o OCR viu e nao conseguiu ler: registra o buraco e pede a imagem de novo.

    A linha em `comprovantes_do_grupo` existe mesmo sem valor: sem ela, um comprovante ilegivel
    seria indistinguivel de um comprovante que nunca chegou — e a modelo diria "eu mandei" com
    razao, sem nada no sistema para mostrar.
    """
    comprovante = await registrar_comprovante(
        conn,
        grupo_id=grupo.id,
        mensagem_id=_exigir_mensagem(base),
        classificacao="ilegivel",
        pagador=leitura.pagador,
        chave_destino=leitura.chave_destino,
        titular_destino=leitura.titular_destino,
    )
    if comprovante is None:  # pragma: no cover - reentrega concorrente da mesma imagem
        GRUPO_FINANCEIRO_COMPROVANTES.labels("duplicado").inc()
        return _sem_venda(base, "comprovante_duplicado")

    GRUPO_FINANCEIRO_COMPROVANTES.labels("ilegivel").inc()
    _logger.info(
        "grupo_financeiro_comprovante_ilegivel comprovante_id=%s mensagem_id=%s",
        comprovante.id,
        base.mensagem_id,
    )
    await _postar(enviar, PEDIDO_DE_REENVIO)
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=base.modelo_id,
        mensagem_id=base.mensagem_id,
        comprovante_id=comprovante.id,
        resposta=PEDIDO_DE_REENVIO,
        motivo="comprovante_ilegivel",
    )


async def _papel_do_destino(
    conn: AsyncConnection[Any], leitura: LeituraDoComprovante
) -> PapelResolvido:
    """De quem e a chave para onde este comprovante foi? (ADR-0049 §1, ticket 03)

    Substitui o booleano `chave_e_conhecida`, que respondia "esta na lista da casa" e por isso
    juntava num aviso so a chave da propria modelo (informacao que resolve o bolso da venda) e a
    chave de um terceiro qualquer (ruido) — o gestor aprendia a ignorar o ⚠️ porque ele disparava
    igual nos dois.

    Le o registro INTEIRO, inclusive as chaves inativas: inativar nunca deletar, e a conta que a
    casa encerrou mes passado continua sendo a conta da casa no comprovante de tres semanas atras.
    Autorizar destino NOVO e outra pergunta, e quem a faz e `workers/pix.py`.

    Chave que o OCR nao leu volta `desconhecida` — closed-world, nunca casa por acidente.
    """
    return papel_da_chave(leitura.chave_destino, await registro_de_chaves(conn))


def _e_entrada_da_modelo(
    leitura: LeituraDoComprovante,
    *,
    nomes_dela: Collection[str],
    pagador_e_a_modelo: bool,
    destino_e_dela: bool,
) -> bool:
    """Este comprovante aponta para o lado CONTRARIO — o cliente pagando a modelo?

    Vem do export real (06/08): a gestora postou no grupo o Pix de R$ 658,07 que a cliente Vanessa
    fez PARA a Yasmin. O agente lia aquilo como transferencia dela, perguntava "é de quê?" e ainda
    disparava o alarme de chave fora da lista — apontando, como suspeito, o nome da propria modelo.
    Com uma venda em pix aberta na fila, teria feito pior: abatido, e dado por comprovado dinheiro
    que a casa nao recebeu.

    Duas condicoes, e sao as duas juntas que valem: **quem recebeu e ela** (`destino_e_dela`, ou o
    primeiro nome do titular) **e quem pagou nao e ela**. So o destino nao basta — num fechamento
    legitimo a pagadora e ela, e uma casa cujo titular tenha o mesmo primeiro nome passaria a nunca
    abater nada.

    `destino_e_dela` chega pronto do chamador (ticket 03) porque a resposta agora tem duas fontes —
    o papel `modelo` no registro de chaves e a chave que o grupo ensinou em `dados_cadastrais` — e
    resolve-las duas vezes na mesma passada seria duas consultas e duas chances de discordar.

    `nomes_dela` e `pagador_e_a_modelo` chegam prontos pelo mesmo motivo (ticket 04): a irma desta
    funcao (`e_do_cliente_para_a_casa`) pergunta "quem pagou nao e ela?" com as MESMAS palavras, e
    duas leituras do cadastro de nomes na mesma passada seriam duas chances de as duas classes
    discordarem sobre quem e a modelo. Sem banco aqui dentro: a decisao virou dado.
    """
    if pagador_e_a_modelo:
        return False
    if destino_e_dela:
        return True
    return nome_e_da_modelo(leitura.titular_destino, nomes_dela)


async def _registrar_entrada_da_modelo(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    leitura: LeituraDoComprovante,
    valor: Decimal,
    recebida_em: datetime,
    conteudo_hash: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """Guarda o comprovante como entrada e diz UMA linha — sem abater, sem quitar, sem perguntar.

    Fica registrado (e nao ignorado) porque ele e prova de que a venda foi paga: quem for conferir
    o extrato precisa ver que o dinheiro existe e onde ele parou. O que ele nao pode e mover o
    eixo do fechamento, que mede o que saiu da mao dela para a casa.

    **E ele que fixa o BOLSO em `dela`** (ticket 04): "onde o dinheiro parou" e exatamente a
    pergunta do bolso, e este comprovante e a resposta por escrito — o cliente pagou na chave dela,
    entao o bruto ficou na mao dela e o razao debita, como debitaria num fechamento. A venda
    continua na fila do abate (`vendas_pix_a_comprovar` so exclui `empresa`), e continua mesmo:
    ela recebeu o valor cheio e deve o valor cheio (ADR-0047, *"o certo vai ser ela receber e
    enviar pra gente"*).
    """
    comprovante = await registrar_comprovante(
        conn,
        grupo_id=grupo.id,
        mensagem_id=_exigir_mensagem(base),
        classificacao="entrada_da_modelo",
        valor=valor,
        data_transferencia=leitura.data,
        pagador=leitura.pagador,
        chave_destino=leitura.chave_destino,
        titular_destino=leitura.titular_destino,
        chave_conhecida=False,
        conteudo_hash=conteudo_hash,
    )
    if comprovante is None:
        return await _comprovante_repetido(
            conn, grupo=grupo, base=base, conteudo_hash=conteudo_hash, enviar=enviar
        )
    GRUPO_FINANCEIRO_COMPROVANTES.labels("entrada_da_modelo").inc()
    _logger.info(
        "grupo_financeiro_comprovante_entrada comprovante_id=%s grupo_id=%s valor=%s pagador=%s",
        comprovante.id,
        grupo.id,
        valor,
        leitura.pagador,
    )
    falas = [
        montar_aviso_de_entrada_da_modelo(valor=valor, data=leitura.data, pagador=leitura.pagador)
    ]
    fixada, sobre_o_bolso = await _bolso_do_comprovante(
        conn,
        grupo=grupo,
        base=base,
        valor=valor,
        recebida_em=recebida_em,
        resolvido=resolver_bolso(comprovante_do_cliente_para_a_modelo=True),
    )
    if sobre_o_bolso is not None:
        falas.append(sobre_o_bolso)
    resposta = "\n".join(falas)
    await _postar(enviar, resposta)
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=grupo.modelo_id,
        mensagem_id=base.mensagem_id,
        comprovante_id=comprovante.id,
        bolsos=(fixada,) if fixada is not None else (),
        resposta=resposta,
        motivo="comprovante_entrada_da_modelo",
    )


async def _bolso_do_comprovante(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    valor: Decimal,
    recebida_em: datetime,
    resolvido: BolsoResolvido,
) -> tuple[UUID | None, str | None]:
    """A ponte entre as duas classes que nao abatem e o bolso da venda que elas explicam.

    Sem venda de valor exato na janela nao acontece nada, e nao ha o que dizer: o comprovante fica
    de prova e o bolso segue `nao_dito`, que e estado legitimo (ADR-0047 §3) e ja tem canal proprio
    — a cobranca consolidada da manha. Inventar aqui a venda mais parecida seria pendurar o sinal
    do saldo num palpite.
    """
    venda = await _venda_do_comprovante(conn, modelo_id=grupo.modelo_id, valor=valor)
    if venda is None:
        return None, None
    return await _fixar_bolso(
        conn,
        base=base,
        grupo_id=grupo.id,
        recebida_em=recebida_em,
        venda=venda,
        resolvido=resolvido,
    )


async def _registrar_cliente_para_a_casa(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    leitura: LeituraDoComprovante,
    valor: Decimal,
    dia: date,
    recebida_em: datetime,
    conteudo_hash: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """O cliente pagou a CASA direto: nao abate, nao quita — fixa o bolso da venda em `empresa`.

    Irma de `_registrar_entrada_da_modelo` e escrita no mesmo formato de proposito: as duas sao a
    tabela de duas pernas (quem pagou x quem recebeu) com o destino trocado, e as duas precisam da
    mesma defesa — a pergunta do comprovante sem par ("é de quê?") e o ⚠️ de chave fora da lista
    diriam, os dois, que ela tem uma transferencia para explicar. Ela nao tem. Quem tem que
    explicar essa e a venda.

    O que este comprovante NAO faz e tao decisivo quanto o que ele faz:

    * **nao abate venda em pix.** Ele nao e transferencia dela — ela nao transferiu nada. Ate o
      ticket 04 ele virava `fechamento` e baixava a venda, o que fechava a conta pelo motivo
      errado: a venda saia da fila como comprovada e o bruto continuava debitado dela;
    * **nao quita Cobranca da agencia.** O destino de uma cobranca e a agencia, nao a casa.

    O que ele faz e tirar do razao o debito de um bruto que ela nunca teve na mao — e a venda sai
    da fila do abate por consequencia, porque `vendas_pix_a_comprovar` exclui `bolso = 'empresa'`:
    nao ha transferencia dela a esperar por um dinheiro que nunca esteve com ela.

    **A ficha aberta de valor exato vira venda aqui tambem**, e com `da_casa=False` — que nao e um
    detalhe de argumento. `bolso_da_promocao` le esse parametro como "comprovante DELA para a
    casa", e passa-lo ligado faria a venda nascer com bolso `dela`, que e o contrario do que este
    comprovante prova. Ela nasce `nao_dito` e o bolso e fixado logo abaixo, pela evidencia certa e
    com o de->para no recibo. Sem esta promocao, o pagamento que o cliente fez direto a casa
    deixaria de virar receita — e a ficha ficaria aberta esperando um gesto que ja aconteceu.
    """
    comprovante = await registrar_comprovante(
        conn,
        grupo_id=grupo.id,
        mensagem_id=_exigir_mensagem(base),
        classificacao="cliente_para_a_casa",
        valor=valor,
        data_transferencia=leitura.data,
        pagador=leitura.pagador,
        chave_destino=leitura.chave_destino,
        titular_destino=leitura.titular_destino,
        chave_conhecida=True,
        conteudo_hash=conteudo_hash,
    )
    if comprovante is None:
        return await _comprovante_repetido(
            conn, grupo=grupo, base=base, conteudo_hash=conteudo_hash, enviar=enviar
        )
    GRUPO_FINANCEIRO_COMPROVANTES.labels("cliente_para_a_casa").inc()
    _logger.info(
        "grupo_financeiro_comprovante_cliente_para_a_casa comprovante_id=%s grupo_id=%s valor=%s "
        "pagador=%s",
        comprovante.id,
        grupo.id,
        valor,
        leitura.pagador,
    )
    await _promover_ficha_do_comprovante(
        conn, grupo=grupo, base=base, valor=valor, dia=dia, da_casa=False
    )
    falas = [
        montar_aviso_de_cliente_para_a_casa(valor=valor, data=leitura.data, pagador=leitura.pagador)
    ]
    fixada, sobre_o_bolso = await _bolso_do_comprovante(
        conn,
        grupo=grupo,
        base=base,
        valor=valor,
        recebida_em=recebida_em,
        resolvido=resolver_bolso(comprovante_do_cliente_para_a_casa=True),
    )
    if sobre_o_bolso is not None:
        falas.append(sobre_o_bolso)
    resposta = "\n".join(falas)
    await _postar(enviar, resposta)
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=grupo.modelo_id,
        mensagem_id=base.mensagem_id,
        comprovante_id=comprovante.id,
        bolsos=(fixada,) if fixada is not None else (),
        resposta=resposta,
        motivo="comprovante_cliente_para_a_casa",
    )


async def _conciliar_comprovante(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    leitura: LeituraDoComprovante,
    valor: Decimal,
    dia: date,
    recebida_em: datetime,
    conteudo_hash: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """Abate FIFO o que este comprovante cobre, e fala UMA vez sobre o que fez.

    A chave desconhecida e checada ANTES do abate e nao o interrompe em momento nenhum: ela vira
    uma linha a mais na mesma mensagem. Travar aqui seria transformar o sinal de fraude em
    paralisia da operacao — e o comprovante que vai para a chave errada e, justamente, dinheiro
    que ja saiu.

    Essa linha a mais sai UMA vez por destino (ticket 05): da segunda aparicao em diante a chave
    desconhecida vira sugestao de cadastro no painel, e o grupo fica calado sobre ela. O que
    silencia e so a FALA — a linha, a flag `chave_conhecida`, a metrica e o log continuam iguais.
    """
    papel = await _papel_do_destino(conn, leitura)
    conhecida = papel.e_da_casa
    # Quem PAGOU e ela? A pergunta e a mesma para as duas classes que nao abatem, e por isso o
    # cadastro de nomes e lido UMA vez aqui: `entrada_da_modelo` (o cliente pagou na chave dela) e
    # `cliente_para_a_casa` (o cliente pagou na chave da casa) sao a mesma tabela de duas pernas —
    # quem pagou x quem recebeu — com o destino trocado. Duas leituras seriam duas chances de as
    # duas classes discordarem sobre quem e a modelo.
    nomes_dela = (await carregar_cadastro_de_nomes(conn)).nomes_de(grupo.modelo_id)
    pagador_e_a_modelo = nome_e_da_modelo(leitura.pagador, nomes_dela)
    # A chave da PROPRIA modelo (ticket 12) nao e da casa e nem deve ser — se fosse, um Pix para a
    # conta dela passaria por fechamento da casa. Ela serve para dizer de QUEM e o destino: o aviso
    # deixa de ser "chave fora da lista, pode ser golpe" e passa a ser "esse dinheiro foi pra conta
    # dela", que e a conversa certa com o gestor.
    #
    # Duas fontes dizem que a chave e dela, e as duas contam: o papel `modelo` no registro (o
    # gestor cadastrou na aba) e a chave que o proprio grupo ensinou (`dados_cadastrais`, ticket
    # 12). O registro nao substitui a segunda — ele aprende devagar, e o grupo aprende de graca.
    da_modelo = False
    if not conhecida:
        da_modelo = papel.e_da_modelo(grupo.modelo_id)
    if not conhecida and not da_modelo:
        cadastrada = await dado_cadastral_atual(conn, grupo.modelo_id, "chave_pix")
        da_modelo = cadastrada is not None and e_a_chave_da_modelo(
            leitura.chave_destino, cadastrada.valor
        )
    if not conhecida and _e_entrada_da_modelo(
        leitura,
        nomes_dela=nomes_dela,
        pagador_e_a_modelo=pagador_e_a_modelo,
        destino_e_dela=da_modelo,
    ):
        return await _registrar_entrada_da_modelo(
            conn,
            grupo=grupo,
            base=base,
            leitura=leitura,
            valor=valor,
            recebida_em=recebida_em,
            conteudo_hash=conteudo_hash,
            enviar=enviar,
        )
    # O cliente pagou a CASA direto (ticket 04): o dinheiro nunca passou pela mao dela. Decidido
    # ANTES do abate e antes da promocao da ficha, e as duas ordens sao a mesma decisao — este
    # comprovante nao e transferencia dela, entao nao pode fechar venda em pix nem nascer uma
    # venda com bolso `dela`. O que ele faz e fixar o bolso em `empresa`, que e o que tira do razao
    # o debito de um bruto que ela nunca teve na mao.
    if conhecida and e_do_cliente_para_a_casa(
        leitura, pagador_e_a_modelo=pagador_e_a_modelo, destino_e_da_casa=True
    ):
        return await _registrar_cliente_para_a_casa(
            conn,
            grupo=grupo,
            base=base,
            leitura=leitura,
            valor=valor,
            dia=dia,
            recebida_em=recebida_em,
            conteudo_hash=conteudo_hash,
            enviar=enviar,
        )
    # A ficha aberta de valor exato vira venda ANTES de a fila ser lida (ticket 07): o mesmo Pix
    # que prova o pagamento e o que faz a venda nascer, e o abate FIFO logo abaixo a fecha na
    # mesma passada. Calada — quem fala neste turno e a confirmacao do abate.
    await _promover_ficha_do_comprovante(
        conn, grupo=grupo, base=base, valor=valor, dia=dia, da_casa=conhecida
    )
    abertas = await vendas_pix_a_comprovar(conn, grupo.modelo_id)
    plano = planejar_abate(valor, abertas)

    # A Cobranca da agencia (ticket 08) e decidida ANTES de o comprovante virar linha: o mesmo Pix
    # nao pode quitar a divida e abater venda, e e o valor exato contra as cobrancas abertas que
    # decide de qual eixo ele e. Quando ele serviria para os dois, o casamento volta `ambigua` e
    # nada e abatido — o comprovante fica retido com a pergunta que nomeia a cobranca.
    casamento = escolher_cobranca(
        valor=valor,
        abertas=await cobrancas_abertas_da_modelo(conn, grupo.modelo_id),
        abate_venda=bool(plano.abatidas),
    )
    if casamento.quitada is not None or casamento.ambigua is not None:
        return await _conciliar_com_cobranca(
            conn,
            grupo=grupo,
            base=base,
            leitura=leitura,
            valor=valor,
            casamento=casamento,
            conhecida=conhecida,
            conteudo_hash=conteudo_hash,
            enviar=enviar,
        )

    classificacao: Classificacao = "fechamento" if plano.abatidas else "nao_classificado"

    comprovante = await registrar_comprovante(
        conn,
        grupo_id=grupo.id,
        mensagem_id=_exigir_mensagem(base),
        classificacao=classificacao,
        valor=valor,
        data_transferencia=leitura.data,
        pagador=leitura.pagador,
        chave_destino=leitura.chave_destino,
        titular_destino=leitura.titular_destino,
        chave_conhecida=conhecida,
        valor_abatido=plano.valor_abatido,
        conteudo_hash=conteudo_hash,
    )
    if comprovante is None:
        # A MESMA foto de novo (reenvio, encaminhamento) ou a mesma mensagem reentregue. O abate
        # ainda nao acontecue — ele vem depois desta linha —, entao nao ha nada a desfazer: o
        # gate do banco e o que impede um Pix de fechar duas vendas. Falar aqui e obrigatorio,
        # senao ela manda uma terceira vez.
        return await _comprovante_repetido(
            conn, grupo=grupo, base=base, conteudo_hash=conteudo_hash, enviar=enviar
        )

    baixadas = await abater_vendas(conn, comprovante.id, [v.id for v in plano.abatidas])
    if len(baixadas) != len(plano.abatidas):
        # Outra entrega fechou parte da fila entre o plano e o abate. O que vale e o que baixou —
        # inclusive o caso em que nao baixou nada e o comprovante deixa de ser fechamento.
        classificacao = "fechamento" if baixadas else "nao_classificado"
        await ajustar_abate(
            conn,
            comprovante.id,
            classificacao=classificacao,
            valor_abatido=_soma(v.valor for v in baixadas),
        )

    # Releitura da fila DEPOIS do abate: o "falta comprovar" que o grupo le tem que ser o numero
    # de agora, nao o que o plano previu antes de escrever.
    restantes = await vendas_pix_a_comprovar(conn, grupo.modelo_id)
    abatido = _soma(v.valor for v in baixadas)
    real = PlanoDeAbate(
        abatidas=tuple(baixadas),
        valor_abatido=abatido,
        sobra=valor - abatido,
        a_comprovar=_soma(v.valor for v in restantes),
    )

    falas = [
        montar_confirmacao_de_abate(real, valor=valor, data=leitura.data)
        if baixadas
        else montar_pergunta_do_comprovante(valor=valor, data=leitura.data)
    ]
    if not conhecida:
        GRUPO_FINANCEIRO_COMPROVANTES.labels(
            "chave_da_modelo" if da_modelo else "chave_desconhecida"
        ).inc()
        # ⚠️ A METRICA E O LOG NAO SAO SILENCIADOS, so a fala (ADR-0049 §5, ticket 05). O que o
        # ticket ataca e o alarme repetido no WhatsApp, que treinou o gestor a ignorar o ⚠️ —
        # nao a observabilidade. O painel continua contando toda passagem por chave fora da casa,
        # e e dele que sai a fila de sugestoes.
        vezes_antes = (
            0
            if da_modelo
            else await vezes_que_o_destino_apareceu(
                conn, leitura.chave_destino, exceto=comprovante.id
            )
        )
        _logger.warning(
            "grupo_financeiro_comprovante_chave_desconhecida comprovante_id=%s grupo_id=%s "
            "da_modelo=%s vezes_antes=%d",
            comprovante.id,
            grupo.id,
            da_modelo,
            vezes_antes,
        )
        if deve_avisar_destino_fora_da_casa(da_modelo=da_modelo, vezes_antes=vezes_antes):
            aviso = (
                montar_aviso_de_chave_da_modelo if da_modelo else montar_aviso_de_chave_desconhecida
            )
            falas.append(aviso(chave=leitura.chave_destino, titular=leitura.titular_destino))
    resposta = "\n".join(falas)
    await _postar(enviar, resposta)

    GRUPO_FINANCEIRO_COMPROVANTES.labels(classificacao).inc()
    _logger.info(
        "grupo_financeiro_comprovante comprovante_id=%s classificacao=%s valor=%s abatidas=%d "
        "chave_conhecida=%s",
        comprovante.id,
        classificacao,
        valor,
        len(baixadas),
        conhecida,
    )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=grupo.modelo_id,
        mensagem_id=base.mensagem_id,
        comprovante_id=comprovante.id,
        abatidas=tuple(v.id for v in baixadas),
        # As vendas que este comprovante fechou saem SEM pendencia — e a prova de que a de
        # comprovante morreu aqui. As que ficaram na fila continuam com a delas, e e a rotina da
        # manha (ticket 10) que volta a cobra-las.
        pendencias=tuple(p for venda in baixadas for p in pendencias_da_venda(venda)),
        resposta=resposta,
        motivo="comprovante_conciliado" if baixadas else "comprovante_nao_classificado",
    )


async def _conciliar_com_cobranca(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    leitura: LeituraDoComprovante,
    valor: Decimal,
    casamento: CasamentoDaCobranca,
    conhecida: bool,
    conteudo_hash: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """O comprovante encontrou uma Cobranca da agencia: quita a divida — e nenhuma venda.

    Dois desfechos, e a diferenca entre eles e o `abate_venda` que o casamento ja pesou:

    * **so a cobranca cabe** -> classificacao `cobranca`, `quitar_cobranca` amarra a prova e a
      confirmacao diz, com todas as letras, que nenhuma venda foi abatida;
    * **caberia nos dois eixos** -> nada e escrito fora do proprio comprovante: ele fica RETIDO
      (`nao_classificado`) com a pergunta que nomeia a cobranca candidata. Chutar aqui moveria
      dinheiro entre dois eixos que nunca mais se cruzam.

    **O aviso de chave fora da lista da casa nao sai por aqui**, e essa e uma decisao, nao um
    esquecimento: o destino de um pagamento de cobranca e a AGENCIA, entao a chave estar fora da
    lista da casa e o normal — repetir o ⚠️ a cada cobranca paga treinaria o grupo a ignorar
    exatamente o alarme que existe para o Pix de fechamento (user story 11). A flag continua no
    banco (`chave_conhecida`) e visivel no painel, que e onde o gestor audita. O que o modulo NAO
    tem e uma lista de chaves da propria agencia: com ela, um pagamento para chave falsa no valor
    exato da cobranca seria pego aqui — sem ela, nao ha o que comparar, e inventar o alarme seria
    palpite.

    **O dedup por foto vale aqui igual ao eixo das vendas**, e o motivo e mais forte do que la: a
    cobranca do portal e SEMANAL e sempre do mesmo valor, entao a foto da semana passada casa
    perfeitamente com a divida desta semana. Sem `conteudo_hash`, a mesma prova quitava duas
    cobrancas (medido em 16/08 pelo `exports/renovacao_da_cobranca`) e o dinheiro que a modelo
    deve a agencia sumia sem deixar rastro no painel — o `valor_abatido` das duas linhas dizia que
    tudo foi pago. O gate do banco devolve `None` ANTES do `quitar_cobranca`, entao a segunda
    entrega nao chega a escrever nada.
    """
    quitando = casamento.quitada
    classificacao: Classificacao = "cobranca" if quitando is not None else "nao_classificado"

    comprovante = await registrar_comprovante(
        conn,
        grupo_id=grupo.id,
        mensagem_id=_exigir_mensagem(base),
        classificacao=classificacao,
        valor=valor,
        data_transferencia=leitura.data,
        pagador=leitura.pagador,
        chave_destino=leitura.chave_destino,
        titular_destino=leitura.titular_destino,
        chave_conhecida=conhecida,
        valor_abatido=quitando.valor if quitando is not None else Decimal("0.00"),
        conteudo_hash=conteudo_hash,
    )
    if comprovante is None:
        # A mesma foto de novo — e no eixo da cobranca ela costuma vir DIAS depois, na renovacao
        # seguinte. Responder e parte do remedio: sem a fala, a modelo acha que a imagem nao
        # chegou, manda uma terceira e a divida continua aberta sem ninguem entender por que.
        return await _comprovante_repetido(
            conn, grupo=grupo, base=base, conteudo_hash=conteudo_hash, enviar=enviar
        )

    quitada = (
        await quitar_cobranca(conn, quitando.id, comprovante.id) if quitando is not None else None
    )
    if quitada is None:
        # Ambiguo, ou a cobranca foi quitada por outro comprovante entre a leitura e o UPDATE. Os
        # dois terminam igual: o comprovante retido com uma pergunta. No segundo caso a linha ja
        # nasceu como `cobranca` e precisa voltar atras — `ajustar_abate` e o mesmo remedio que o
        # caminho das vendas usa quando a fila muda debaixo do plano.
        if classificacao == "cobranca":  # pragma: no cover - corrida entre dois comprovantes
            await ajustar_abate(
                conn,
                comprovante.id,
                classificacao="nao_classificado",
                valor_abatido=Decimal("0.00"),
            )
        alvo = casamento.ambigua or quitando
        resposta = (
            montar_pergunta_do_comprovante_ambiguo(cobranca=alvo, valor=valor, data=leitura.data)
            if alvo is not None
            else montar_pergunta_do_comprovante(valor=valor, data=leitura.data)
        )
        await _postar(enviar, resposta)

        GRUPO_FINANCEIRO_COMPROVANTES.labels("nao_classificado").inc()
        _logger.info(
            "grupo_financeiro_comprovante_ambiguo comprovante_id=%s cobranca_id=%s valor=%s",
            comprovante.id,
            alvo.id if alvo is not None else None,
            valor,
        )
        return ResultadoDaPorta(
            status=base.status,
            grupo_id=base.grupo_id,
            modelo_id=grupo.modelo_id,
            mensagem_id=base.mensagem_id,
            comprovante_id=comprovante.id,
            resposta=resposta,
            motivo="comprovante_nao_classificado",
        )

    resposta = montar_confirmacao_de_quitacao(cobranca=quitada, valor=valor, data=leitura.data)
    await _postar(enviar, resposta)

    GRUPO_FINANCEIRO_COMPROVANTES.labels("cobranca").inc()
    _logger.info(
        "grupo_financeiro_cobranca_quitada cobranca_id=%s comprovante_id=%s modelo_id=%s valor=%s "
        "chave_conhecida=%s",
        quitada.id,
        comprovante.id,
        grupo.modelo_id,
        valor,
        conhecida,
    )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=grupo.modelo_id,
        mensagem_id=base.mensagem_id,
        comprovante_id=comprovante.id,
        # `abatidas` fica VAZIO de proposito: nenhuma venda foi tocada. E o campo que a rotina da
        # manha e o painel leem para saber o que foi comprovado — o dinheiro da cobranca nao pode
        # aparecer ali.
        cobrancas_quitadas=(quitada.id,),
        resposta=resposta,
        motivo="comprovante_de_cobranca",
    )


def _soma(valores: Iterable[Decimal]) -> Decimal:
    return sum(valores, Decimal("0.00"))


# --- em que bolso o dinheiro caiu (ADR-0047, ticket 04) ------------------------------------------
#
# O `bolso.py` inteiro estava pronto e sem chamador: nenhum caminho de producao gravava
# `bolso = 'empresa'`. A venda que o cliente pagou direto na conta da casa ficava `nao_dito`, o
# razao a tratava como `dela` pelo default conservador (ADR-0047 §4) e DEBITAVA DELA UM BRUTO QUE
# ELA NUNCA TEVE. Este e o pedaco da porta que liga a tabela de evidencia ao banco.
#
# Tres bocas alimentam a mesma funcao, e e de proposito que seja uma so: o comprovante do cliente
# para a casa (`empresa`), o comprovante do cliente para a chave DELA (`dela`) e a fala explicita
# ("ficou com voce"). Cada uma resolve a evidencia do seu jeito; a partir de `resolver_bolso` o
# caminho e o mesmo — confrontar o que ja esta na coluna, escrever por compare-and-swap e falar o
# de->para. Duas escritas de bolso com condutas diferentes seria o agente respondendo coisas
# diferentes ao mesmo fato conforme o canal por onde ele chegou.


async def _fixar_bolso(
    conn: AsyncConnection[Any],
    *,
    base: ResultadoDaPorta,
    grupo_id: UUID,
    recebida_em: datetime,
    venda: VendaComBolso,
    resolvido: BolsoResolvido,
    contexto: Sequence[MensagemRegistrada] | None = None,
) -> tuple[UUID | None, str | None]:
    """Escreve o bolso desta venda pela evidencia que chegou. Devolve (venda fixada, fala).

    Os dois lados do par sao independentes e os tres pares acontecem: `(id, recibo)` quando a
    evidencia resolveu, `(None, pergunta)` quando ela contradiz um bolso ja afirmado, e
    `(None, None)` quando nao havia o que escrever nem o que dizer. Quem chama compoe a fala com o
    que ele mesmo ja tinha a dizer — o aviso do comprovante e o de->para do bolso saem na MESMA
    mensagem, e nao em duas.

    **A pergunta so sai uma vez por janela de contexto.** `PREFIXO_DA_PERGUNTA_DO_BOLSO` no log do
    grupo e a tranca, a mesma de `_ja_perguntou_de_qual_venda`: sem ela, cada comprovante novo
    sobre a mesma venda reperguntaria, e a metralhadora e o que o dominio proibe. O log so e lido
    quando a conduta E perguntar — no caso comum (`nao_dito` -> evidencia) nao ha consulta nenhuma.

    **`definir_bolso_da_venda` devolvendo `None` nao e falha: e a corrida.** A coluna deixou de ser
    o que este chamador viu entre a leitura e o UPDATE (o comprovante e a fala chegando no mesmo
    segundo). Cai na mesma conduta da divergencia — perguntar —, porque e literalmente o mesmo
    fato: duas evidencias discordando sobre o sinal do saldo dela. A venda e RELIDA antes disso:
    perguntar com o valor velho na mao nomearia um bolso que ja nao e o da coluna, e "esta anotado
    como X" e o unico fato que quem responde pode conferir na tela.
    """
    mudanca = confrontar_bolso(venda.bolso, resolvido)
    if mudanca.conduta == "nada":
        return None, None

    if mudanca.conduta == "fixar":
        escrita = await definir_bolso_da_venda(
            conn, venda.id, de=mudanca.de, para=mudanca.para, mensagem_id=base.mensagem_id
        )
        if escrita is not None:
            await registrar_evento_do_bolso(
                conn, venda.id, de=mudanca.de, para=mudanca.para, mensagem_id=base.mensagem_id
            )
            GRUPO_FINANCEIRO_ANUNCIOS.labels("bolso_fixado").inc()
            _logger.info(
                "grupo_financeiro_bolso_fixado venda_id=%s de=%s para=%s evidencia=%s "
                "mensagem_id=%s",
                venda.id,
                mudanca.de,
                mudanca.para,
                mudanca.evidencia,
                base.mensagem_id,
            )
            return venda.id, montar_recibo_do_bolso(
                mudanca, valor=venda.valor, cliente_nome=venda.cliente_nome
            )
        # Perdeu a corrida: outra evidencia escreveu a coluna entre a leitura e o UPDATE.
        atual = await venda_para_o_bolso(conn, venda.id)
        if atual is None:  # pragma: no cover - venda anulada entre a leitura e o UPDATE
            return None, None
        venda = atual
        mudanca = confrontar_bolso(venda.bolso, resolvido)
        if mudanca.conduta != "perguntar":
            # A outra evidencia escreveu o MESMO bolso (ou a venda foi anulada). Nao ha
            # divergencia nenhuma a levar ao grupo — e o eco que o modulo se proibe.
            return None, None

    if contexto is None:
        contexto = await _contexto_do_grupo_em(
            conn, grupo_id=grupo_id, base=base, recebida_em=recebida_em
        )
    if _ja_perguntou_pelo_bolso(contexto):
        return None, None

    GRUPO_FINANCEIRO_ANUNCIOS.labels("bolso_divergente").inc()
    _logger.warning(
        "grupo_financeiro_bolso_divergente venda_id=%s anotado=%s evidencia_diz=%s por=%s",
        venda.id,
        mudanca.de,
        mudanca.para,
        mudanca.evidencia,
    )
    return None, montar_pergunta_do_bolso(
        mudanca, valor=venda.valor, cliente_nome=venda.cliente_nome
    )


def _ja_perguntou_pelo_bolso(contexto: Sequence[MensagemRegistrada]) -> bool:
    """O agente ja perguntou de qual bolso, no que se ve do grupo?

    `in` e nao `startswith`, ao contrario de `_ja_perguntou_de_qual_venda`: a pergunta do bolso
    viaja como uma LINHA de uma mensagem que costuma comecar pelo aviso do comprovante. Ancorar no
    inicio faria a tranca nunca fechar justamente no caminho que mais repete — o da imagem.
    """
    return any(m.de_mim and PREFIXO_DA_PERGUNTA_DO_BOLSO in m.texto for m in contexto)


async def _venda_do_comprovante(
    conn: AsyncConnection[Any], *, modelo_id: UUID, valor: Decimal
) -> VendaComBolso | None:
    """Qual venda este comprovante esta explicando? So valor EXATO, e so se for uma so.

    A mesma disciplina de `_promover_ficha_do_comprovante`, e pelo mesmo motivo: casar por
    aproximacao penduraria o bolso na venda de outro atendimento, e ninguem reconfere um campo que
    o sistema preencheu sozinho. Duas vendas do mesmo valor na janela (o "600 + 600" real do
    export) nao decidem nada — o bolso fica `nao_dito`, que e estado legitimo e entra na cobranca
    da manha.

    A janela e a de `vendas_para_o_bolso` (as recentes da modelo, afirmadas e nao ditas juntas): a
    afirmada precisa estar aqui para a evidencia que a contradiz virar pergunta em vez de cair
    calada na venda vizinha.
    """
    candidatas = [v for v in await vendas_para_o_bolso(conn, modelo_id) if v.valor == valor]
    return candidatas[0] if len(candidatas) == 1 else None


async def _absorver_bolso(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    texto: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """A terceira linha da tabela: alguem DISSE onde o dinheiro caiu. `None` = nao disse nada.

    Devolve `None` tambem quando disse e o agente nao conseguiu agir — sem venda na janela, fala
    ambigua, pergunta ja feita. E deliberado: assumir o turno sem ter escrito nada tiraria da
    mensagem as outras chances que ela tem na cascata, e "ficou com voce" numa conversa em que
    nao ha venda para apontar e conversa. So o que ESCREVE (ou pergunta) fica com o turno.

    Mora no `_conduzir`, e nao dentro de `_absorver_resposta`, por causa do teto de palavras: a
    triagem de custo de la e de 8 palavras (a forma se diz numa so) e a fala de bolso tem teto
    proprio de 12 ("o dinheiro do Ramon ficou com voce" tem 7, mas "o do cliente de ontem caiu na
    conta da casa" tem 10). `ler_fala_de_bolso` e puro e nao custa consulta nenhuma — o banco so e
    tocado depois que a frase casou.
    """
    fala = ler_fala_de_bolso(texto)
    if fala is None:
        return None

    candidatas = await vendas_para_o_bolso(conn, grupo.modelo_id)
    if not candidatas:
        return None
    citada: UUID | None = None
    if msg.quoted_message_id:
        # O quote e o primeiro degrau da escada (`escolher_venda_do_bolso`), e aqui ele vale por
        # duas mensagens: o anuncio e o recibo que o agente postou citando o anuncio — que e o que
        # o proprio recibo convida a responder.
        citadas = await vendas_da_mensagem_citada(conn, grupo.id, msg.quoted_message_id)
        if len(citadas) == 1:
            citada = citadas[0].id
    contexto = await _contexto_do_grupo(conn, msg, grupo_id=grupo.id, base=base)
    escolha = escolher_venda_do_bolso(
        texto=texto, contexto=contexto, candidatas=candidatas, venda_citada=citada
    )
    if escolha.venda is None:
        # Ambigua: o agente NAO pergunta "em qual?" aqui. A pergunta de desempate existe para a
        # forma de pagamento porque a forma trava a venda; o bolso nao trava nada — ele entra na
        # cobranca consolidada da manha, que ja nomeia cada venda e ja e o canal desta duvida.
        _logger.info(
            "grupo_financeiro_bolso_sem_alvo grupo_id=%s motivo=%s frase=%s",
            grupo.id,
            escolha.motivo,
            fala.frase,
        )
        return None

    fixada, resposta = await _fixar_bolso(
        conn,
        base=base,
        grupo_id=grupo.id,
        recebida_em=msg.recebida_em,
        venda=escolha.venda,
        resolvido=resolver_bolso(fala=fala.bolso),
        contexto=contexto,
    )
    if resposta is None:
        return None
    await _postar(enviar, resposta)
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=grupo.modelo_id,
        mensagem_id=base.mensagem_id,
        bolsos=(fixada,) if fixada is not None else (),
        resposta=resposta,
        motivo="bolso_fixado" if fixada is not None else "bolso_divergente",
    )


# --- correcao por quote no recibo ---------------------------------------------------------------


async def _corrigir_por_quote(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """A mensagem responde um recibo (ou o anuncio) corrigindo um campo? `None` = nao e correcao.

    Efeito imediato e sem confirmacao, pelo mesmo motivo do registro direto: quem afirmou o fato
    foi o humano do grupo. O que a correcao acrescenta e o **de→para** no eco — corrigir um dado
    ja conferido e a unica operacao do modulo em que um numero certo pode virar errado sem deixar
    marca na tela, e o eco e a marca.
    """
    if not msg.quoted_message_id:
        return None
    vendas = await vendas_da_mensagem_citada(conn, grupo.id, msg.quoted_message_id)
    if not vendas:
        return None

    correcao = ler_correcao(msg.texto or msg.caption or "", referencia=msg.dia_brt())
    if correcao is None:
        return None
    campos = correcao.campos()
    if campos == ("forma_pagamento",) and any(v.forma_pagamento is None for v in vendas):
        # Dizer a forma pela PRIMEIRA vez nao e correcao, e a absorcao do ticket 03 — ela responde
        # com o recibo de pagamento e fecha a Pendencia. Correcao e trocar o que ja estava dito.
        return None

    alvos = _alvos_da_correcao(vendas, campos)
    if alvos is None:
        await _postar(enviar, AVISO_DE_CORRECAO_AMBIGUA)
        return _sem_venda(base, "correcao_ambigua", resposta=AVISO_DE_CORRECAO_AMBIGUA)

    corrigidas: list[VendaRegistrada] = []
    mudancas: tuple[Mudanca, ...] = ()
    esbarrou_em_duplicata = False
    for venda in alvos:
        depois = aplicar_correcao(venda, correcao)
        deste = mudancas_entre(venda, depois)
        if not deste:
            continue
        gravada = await corrigir_venda(
            conn,
            depois,
            # A chave de conteudo segue o FATO: sem recalcular, o dedup continuaria vigiando a
            # venda de R$ 700,00 que nao existe mais, e o repost do anuncio ja corrigido nasceria
            # como uma segunda linha viva.
            chave_conteudo=chave_de_conteudo(
                data=depois.data,
                valor=depois.valor,
                modelo_id=depois.modelo_id,
                cliente=depois.cliente_nome,
            ),
        )
        if gravada is None:
            esbarrou_em_duplicata = True
            continue
        await registrar_eventos_da_venda(
            conn,
            gravada.id,
            tipo="correcao",
            mensagem_id=_exigir_mensagem(base),
            mudancas=deste,
        )
        corrigidas.append(gravada)
        mudancas = mudancas or deste

    if not corrigidas:
        if esbarrou_em_duplicata:
            await _postar(enviar, AVISO_DE_CORRECAO_DUPLICADA)
            return _sem_venda(base, "correcao_duplicada", resposta=AVISO_DE_CORRECAO_DUPLICADA)
        # "foi 650" numa venda que ja esta em 650. Calado de proposito: nao houve evento, e
        # responder "corrigi" a uma correcao que nao corrigiu nada e pior que nao responder.
        return _sem_venda(base, "correcao_sem_efeito")

    eco = montar_eco_de_correcao(mudancas, linhas=len(corrigidas))
    await _postar(enviar, eco)
    for venda in corrigidas:
        GRUPO_FINANCEIRO_ANUNCIOS.labels("venda_corrigida").inc()
        _logger.info(
            "grupo_financeiro_venda_corrigida venda_id=%s campos=%s mensagem_id=%s",
            venda.id,
            [m.campo for m in mudancas],
            base.mensagem_id,
        )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=corrigidas[0].modelo_id if len(corrigidas) == 1 else base.modelo_id,
        mensagem_id=base.mensagem_id,
        correcoes=tuple(venda.id for venda in corrigidas),
        pendencias=tuple(p for venda in corrigidas for p in pendencias_da_venda(venda)),
        resposta=eco,
        motivo="correcao_aplicada",
    )


def _alvos_da_correcao(
    vendas: Sequence[VendaRegistrada], campos: tuple[CampoCorrigivel, ...]
) -> list[VendaRegistrada] | None:
    """Quais linhas do recibo esta correcao atinge. `None` = nao da para saber sem adivinhar.

    Um recibo pode cobrir DUAS Vendas registradas (o anuncio de duas modelos). Cliente, data e
    duracao sao do FATO — corrigir vale para as duas, porque foi um atendimento so. Valor e forma
    de pagamento sao de cada linha: so cabem nas duas quando as duas estao iguais hoje (o caso do
    "cada uma", que e como o grupo escreve). Valores diferentes viram pergunta, nunca palpite —
    escolher errado aqui move dinheiro de uma mulher para a outra.
    """
    if len(vendas) == 1:
        return list(vendas)
    for campo in campos:
        if campo not in CAMPOS_DA_LINHA:
            continue
        distintos = {(v.valor if campo == "valor" else v.forma_pagamento) for v in vendas}
        if len(distintos) > 1:
            return None
    return list(vendas)


# --- fechamento sob comando ---------------------------------------------------------------------


async def fechamento_da_modelo(conn: AsyncConnection[Any], modelo_id: UUID) -> Extrato:
    """O Fechamento da modelo AGORA — vendido x comprovado x em especie, e o que nao bate.

    Publica de proposito: e por aqui que a rotina diaria da manha (ticket 10) chega ao mesmo
    extrato que o grupo ve sob comando. Um segundo caminho ate o saldo seria um segundo jeito de a
    conta divergir, e o unico numero que o gestor confere de cabeca hoje nao pode ter duas versoes
    no sistema.

    A composicao em si desceu para `dominio/grupo_financeiro/service.py` (ticket 11): o painel
    precisa do mesmo extrato e `dominio/` nao importa a camada de agente. Esta funcao continua
    sendo a porta do modulo — quem esta do lado do grupo entra por aqui.
    """
    return await extrato_da_modelo(conn, modelo_id)


async def _fechar(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """Alguem pediu o fechamento: posta o extrato (ou o "tudo conciliado") e nao muda nada.

    Leitura pura — pedir o fechamento nunca escreve linha nenhuma, nem resolve pendencia, nem
    marca periodo. E o que garante que pedir duas vezes seguidas devolva a mesma coisa, e que a
    divergencia continue la depois de o agente perguntar sobre ela.
    """
    extrato = await fechamento_da_modelo(conn, grupo.modelo_id)
    resposta = montar_fala_do_fechamento(extrato)
    await _postar(enviar, resposta)

    GRUPO_FINANCEIRO_ANUNCIOS.labels("fechamento_postado").inc()
    _logger.info(
        "grupo_financeiro_fechamento grupo_id=%s modelo_id=%s vendido=%s comprovado=%s "
        "em_especie=%s a_comprovar=%s pendencias=%d divergencias=%s",
        grupo.id,
        grupo.modelo_id,
        extrato.vendido,
        extrato.comprovado,
        extrato.em_especie,
        extrato.a_comprovar,
        len(extrato.pendencias),
        [d.tipo for d in extrato.divergencias],
    )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=grupo.modelo_id,
        mensagem_id=base.mensagem_id,
        pendencias=extrato.pendencias,
        extrato=extrato,
        resposta=resposta,
        motivo="fechamento_postado",
    )


# --- anuncio: registrar, ou perguntar so o que falta --------------------------------------------


async def _lancar_venda_se_for_anuncio(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    extrair: ExtratorDeAnuncio,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    texto = msg.texto or msg.caption or ""
    anuncio = extrair(texto)
    cadastro = await carregar_cadastro_de_nomes(conn)
    plano = planejar(anuncio, cadastro=cadastro, dona_do_grupo=grupo.modelo_id)
    if plano.participante_oculta:
        # Rateio dito ("cada uma", "no total") e uma participante so: o anuncio afirma que houve
        # outra mulher e nao diz qual. Registrar so a nomeada daria o valor de uma a outra que
        # nunca aparece no sistema; perguntar "quem mais?" seria interrogatorio sobre um anuncio
        # que a gestora escreveu pela metade. Silencio com motivo visivel e o meio-termo honesto.
        #
        # Quem decide se e uma participante ou duas e o `planejar`, e nao a contagem de linhas:
        # duas mulheres cadastradas na MESMA linha ("Perfil lari/ juju") sao duas.
        return _sem_venda(base, "varias_modelos")
    if plano.ambiguo and not plano.linhas:
        # Dois cadastros com o mesmo nome. Perguntar "quem?" so devolveria o mesmo nome — isso e
        # erro de cadastro, resolve-se no painel, nao no grupo.
        return _sem_venda(base, "nome_ambiguo", nomes=plano.nomes_desconhecidos)

    contexto: Sequence[MensagemRegistrada] = ()
    if plano.nomes_desconhecidos:
        # So aqui vale relê o grupo: e o unico caso em que a decisao depende do que o AGENTE ja
        # disse (nao perguntar duas vezes pelo mesmo nome).
        contexto = await _contexto_do_grupo(conn, msg, grupo_id=grupo.id, base=base)

    return await _executar_plano(
        conn,
        base=base,
        plano=plano,
        anuncio=anuncio,
        data=msg.dia_brt(),
        mensagem_id=_exigir_mensagem(base),
        contexto=contexto,
        enviar=enviar,
    )


async def _contexto_do_grupo(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo_id: UUID,
    base: ResultadoDaPorta,
) -> list[MensagemRegistrada]:
    """O log do grupo imediatamente antes desta mensagem — o estado conversacional do modulo.

    Recebe o `grupo_id` e nao o `GrupoFinanceiro`: o log de origem e do GRUPO, e o Grupo de fichas
    (que nao tem dona) tem o dele — e e nele que mora a tranca contra reperguntar pelo mesmo nome.
    """
    return await _contexto_do_grupo_em(
        conn, grupo_id=grupo_id, base=base, recebida_em=msg.recebida_em
    )


async def _contexto_do_grupo_em(
    conn: AsyncConnection[Any],
    *,
    grupo_id: UUID,
    base: ResultadoDaPorta,
    recebida_em: datetime,
) -> list[MensagemRegistrada]:
    """O mesmo log, para quem tem o RELOGIO da mensagem e nao a mensagem inteira.

    O caminho da imagem (`_conciliar_comprovante` e as duas classes que nao abatem) carrega o dia
    do comprovante, nunca o `MensagemDoGrupo` — e a tranca da pergunta do bolso precisa do log
    exatamente como as outras trancas do modulo precisam.
    """
    return await mensagens_recentes(
        conn,
        grupo_id,
        antes_de=recebida_em,
        antes_da_mensagem=_exigir_mensagem(base),
        desde=recebida_em - JANELA_DE_CONTEXTO,
        limite=MENSAGENS_DE_CONTEXTO,
    )


# --- ficha do telefonista: gravar o combinado, calado -------------------------------------------


async def _registrar_ficha_se_for_card(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo_id: UUID,
    dona_do_grupo: UUID | None,
    base: ResultadoDaPorta,
    texto: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """Um dos tres documentos do telefonista? Grava a ficha e cala. `None` = nao e ficha.

    **Sem recibo, sempre** (ADR-0044 §1): o telefonista nao pediu confirmacao de nada, e um "✅
    Registrei" a cada card transformaria o grupo de fichas num eco. A UNICA fala possivel deste
    caminho e pergunta: pelo nome que o cadastro nao conhece, pela divergencia entre o card e a
    dona do grupo, ou pelo comunicado que casa com duas fichas. Todas com a mesma tranca contra
    repetir.

    `dona_do_grupo=None` e o **Grupo de fichas** (ADR-0046 §2): la nao ha de quem herdar, e o card
    que nao nomeia ninguem nao vira ficha nenhuma. Recebe a dona (e nao o `GrupoFinanceiro`)
    porque e literalmente o unico uso do grupo aqui — e escrever isso no tipo e o que impede o
    caminho novo de voltar a deduzir a modelo pelo JID.

    A ficha e gravada mesmo incompleta: ela **nao e receita** e nenhuma coluna dela e obrigatoria
    fora da mensagem-fonte. O que falta vira campo nulo, e o campo nulo vira a pergunta consolidada
    da manha — nunca um interrogatorio no ato.
    """
    lida = ler_ficha(texto, hoje=msg.dia_brt())
    if lida is None:
        return None
    if not lida.tem_conteudo:
        # O template em branco, repostado para alguem copiar. Casa todos os rotulos e nao afirma
        # fato nenhum; gravar criaria um atendimento previsto que ninguem combinou.
        return _com_ficha(base, ficha_id=None, motivo="ficha_sem_conteudo")

    cadastro = await carregar_cadastro_de_nomes(conn)
    plano = planejar_ficha(lida, cadastro=cadastro, dona_do_grupo=dona_do_grupo)

    if not plano.participantes:
        if plano.ambiguo:
            # Dois cadastros com o mesmo nome. Perguntar "quem?" so devolveria o mesmo nome —
            # erro de cadastro se resolve no painel, nao no grupo (igual ao anuncio).
            return _com_ficha(
                base,
                ficha_id=None,
                motivo="ficha_nome_ambiguo",
                nomes=plano.nomes_desconhecidos,
            )
        if not plano.nomes_desconhecidos:
            # O card nao nomeia ninguem E nao ha dona de quem herdar — o Grupo de fichas com o
            # campo `Nome da modelo` em branco (ticket 19). Nao ha nome para perguntar por
            # ("'?' e quem?" nao se responde), entao a conduta e o silencio de sempre: o card fica
            # no log de origem e o telefonista reposta com o nome, o que cai no dedup por conteudo.
            return _com_ficha(base, ficha_id=None, motivo="ficha_sem_modelo")

    pergunta = await _perguntar_pelos_nomes_da_ficha(
        conn,
        msg,
        grupo_id=grupo_id,
        base=base,
        plano=plano,
        cliente=lida.cliente_nome,
        enviar=enviar,
    )
    if not plano.participantes:
        return _com_ficha(
            base,
            ficha_id=None,
            motivo="ficha_nome_desconhecido",
            nomes=plano.nomes_desconhecidos,
            resposta=pergunta,
        )

    if plano.divergencia is not None:
        # O card caiu no grupo de uma modelo e nomeia SO outras. Gravar pela dona registraria o
        # atendimento da Duda no nome da Yasmin; gravar pelo card poria a ficha da Duda dentro do
        # grupo da Yasmin. As duas saidas silenciosas erram, e uma delas fura o isolamento
        # cross-modelo — entao vira pergunta, e nada e escrito enquanto ninguem responder.
        divergente = await _perguntar_pela_divergencia(
            conn, msg, grupo_id=grupo_id, base=base, divergencia=plano.divergencia, enviar=enviar
        )
        return _com_ficha(base, ficha_id=None, motivo="ficha_de_outra_modelo", resposta=divergente)

    if lida.documento == "comunicado":
        vinculada = await _comunicado_da_ficha_existente(
            conn, msg, lida, grupo_id=grupo_id, base=base, plano=plano, enviar=enviar
        )
        if vinculada is not None:
            return vinculada

    chave = chave_de_conteudo_da_ficha(
        data=lida.data,
        hora=lida.hora,
        cliente=lida.cliente_nome,
        modelo_ids=[p.modelo_id for p in plano.participantes],
    )
    ficha = await registrar_ficha(
        conn,
        lida=lida,
        participantes=plano.participantes,
        mensagem_id=_exigir_mensagem(base),
        chave_conteudo=chave,
    )
    if ficha is None:
        # O mesmo combinado ja esta gravado: o card repostado, ou postado tambem no grupo da outra
        # participante. Reconhecer sem falar e o certo — o repost que MUDA um campo e o ticket 09.
        existente = await ficha_por_chave_de_conteudo(conn, chave)
        return _com_ficha(
            base,
            ficha_id=existente.id if existente else None,
            motivo="ficha_duplicada",
            resposta=pergunta,
        )

    return _com_ficha(
        base,
        ficha_id=ficha.id,
        motivo="ficha_nome_desconhecido" if plano.nomes_desconhecidos else "ficha_registrada",
        nomes=plano.nomes_desconhecidos,
        resposta=pergunta,
    )


async def _perguntar_pelos_nomes_da_ficha(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo_id: UUID,
    base: ResultadoDaPorta,
    plano: PlanoDaFicha,
    cliente: str | None,
    enviar: EnviarNoGrupo | None,
) -> str | None:
    """ "'fran loira' e quem?" — a mesma pergunta minima do anuncio, com a mesma tranca.

    Le o grupo SO quando ha nome desconhecido: e o unico caso em que a decisao depende do que o
    AGENTE ja disse. Perguntar de novo por um nome que ninguem respondeu ainda e a metralhadora
    que o dominio proibe.

    A ficha de festinha com uma modelo conhecida e outra nao grava a conhecida e pergunta so pela
    outra: falta parcial nunca trava o resto.
    """
    if not plano.nomes_desconhecidos:
        return None
    contexto = await _contexto_do_grupo(conn, msg, grupo_id=grupo_id, base=base)
    if _ja_perguntou_pelos_nomes(contexto, plano.nomes_desconhecidos):
        return None
    pergunta = montar_pergunta_minima(
        faltas=("modelo",),
        cliente=cliente,
        nomes_desconhecidos=plano.nomes_desconhecidos,
    )
    if pergunta is not None:
        await _postar(enviar, pergunta)
    return pergunta


async def _perguntar_pela_divergencia(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo_id: UUID,
    base: ResultadoDaPorta,
    divergencia: DivergenciaDeDona,
    enviar: EnviarNoGrupo | None,
) -> str | None:
    """ "❓ Essa ficha é da Duda ou da Yasmin?" — uma vez por janela de contexto.

    Tranca propria (`PREFIXO_DA_DIVERGENCIA`), pelo motivo de sempre: o card que caiu no grupo
    errado costuma ser repostado igual — o telefonista tenta de novo antes de ler a pergunta —, e
    uma pergunta por repost e a metralhadora que o dominio proibe.
    """
    pergunta = montar_pergunta_da_divergencia(divergencia)
    if pergunta is None:
        return None
    contexto = await _contexto_do_grupo(conn, msg, grupo_id=grupo_id, base=base)
    if any(m.de_mim and m.texto.startswith(PREFIXO_DA_DIVERGENCIA) for m in contexto):
        return None
    await _postar(enviar, pergunta)
    return pergunta


async def _comunicado_da_ficha_existente(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    lida: FichaLida,
    *,
    grupo_id: UUID,
    base: ResultadoDaPorta,
    plano: PlanoDaFicha,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """O comunicado da modelo VINCULA a ficha que ja existe; nunca cria uma segunda.

    Quando a ficha completa vai para o Grupo de fichas, o mesmo atendimento chega duas vezes ao
    sistema — a ficha la e o comunicado aqui. Duas fichas para um atendimento apareceriam duas
    vezes no painel e seriam cobradas duas vezes na manha seguinte.

    `None` = nao ha ficha correspondente, e o comunicado segue para virar a ficha (o arranjo sem
    Grupo de fichas, e o que acontece quando o telefonista pula a ficha completa).

    O casamento e por `modelo + cliente + valor` e nao pela chave de conteudo: o comunicado nao
    tem data. A lista de abertas e a **da modelo** (ADR-0046 §2) — a ficha que ele resume pode ter
    nascido no Grupo de fichas, e filtrar por grupo perderia o alvo justamente no arranjo que a
    reuniao de 20/08 quer testar.
    """
    modelo_id = plano.participantes[0].modelo_id
    abertas = await fichas_abertas_da_modelo(conn, modelo_id)
    veredito, alvo = casar_comunicado(lida, modelo_id=modelo_id, abertas=abertas)
    if veredito == "vincula" and alvo is not None:
        return _com_ficha(base, ficha_id=alvo.id, motivo="comunicado_vinculado")
    if veredito == "ambiguo":
        # Duas fichas abertas dela que o comunicado descreve igual (mesmo cliente, mesmo valor,
        # dias diferentes). Escolher uma seria o palpite que o dominio proibe e criar uma terceira
        # seria pior: vira UMA pergunta, e ela nomeia so as candidatas — sao fichas DELA, com o
        # valor DELA, entao nada de outra modelo aparece.
        pergunta = await _perguntar_pelo_comunicado(
            conn,
            msg,
            grupo_id=grupo_id,
            base=base,
            candidatas=candidatas_do_comunicado(lida, modelo_id=modelo_id, abertas=abertas),
            modelo_id=modelo_id,
            enviar=enviar,
        )
        return _com_ficha(base, ficha_id=None, motivo="comunicado_ambiguo", resposta=pergunta)
    return None


async def _perguntar_pelo_comunicado(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo_id: UUID,
    base: ResultadoDaPorta,
    candidatas: Sequence[FichaDeAgendamento],
    modelo_id: UUID,
    enviar: EnviarNoGrupo | None,
) -> str | None:
    """ "❓ Esse comunicado é de qual atendimento? …" — uma vez por janela de contexto."""
    pergunta = montar_pergunta_do_comunicado_ambiguo(candidatas=candidatas, modelo_id=modelo_id)
    if pergunta is None:  # pragma: no cover - "ambiguo" implica duas candidatas
        return None
    contexto = await _contexto_do_grupo(conn, msg, grupo_id=grupo_id, base=base)
    if any(m.de_mim and m.texto.startswith(PREFIXO_DO_COMUNICADO) for m in contexto):
        return None
    await _postar(enviar, pergunta)
    return pergunta


def _com_ficha(
    base: ResultadoDaPorta,
    *,
    ficha_id: UUID | None,
    motivo: MotivoSemVenda,
    nomes: tuple[str, ...] = (),
    resposta: str | None = None,
) -> ResultadoDaPorta:
    """O resultado de um caminho de FICHA: nenhuma venda, e a ficha que a mensagem tocou."""
    return replace(_sem_venda(base, motivo, nomes=nomes, resposta=resposta), ficha_id=ficha_id)


# --- promocao: o pagamento faz a ficha virar Venda registrada (ticket 07) ------------------------
#
# "recebi, foi dinheiro" as 22h sobre o card do Igor das 19h. A venda nasce ALI, herdando valor,
# cliente, duracao, local e perfil do que o telefonista ja digitou (ADR-0044 §2) — e a modelo nao
# e interrogada sobre nada disso, que e a metralhadora que o dominio proibe.
#
# **A origem do gesto e parametro** (ADR-0046 §5): esta funcao nao sabe se quem falou foi a modelo
# ou o telefonista, e e por isso que o ✅ do ticket 20 reusa este caminho inteiro em vez de abrir
# um segundo lugar que escreve venda. Duas portas para o mesmo fato, uma escrita so.


async def _promover_ficha(
    conn: AsyncConnection[Any],
    *,
    base: ResultadoDaPorta,
    ficha: FichaDeAgendamento,
    modelo_id: UUID,
    forma: FormaPagamento | None,
    origem_do_gesto: OrigemDaPromocao,
    dia: date,
    comprovante_da_modelo: bool = False,
    enviar: EnviarNoGrupo | None,
    falar: bool = True,
    citar: str | None = None,
) -> ResultadoDaPorta:
    """A ficha vira Venda registrada e passa a `realizada`. UMA escrita, para as duas portas.

    `falar=False` e o caminho do COMPROVANTE: la a promocao acontece no meio de um turno que ja
    vai responder o abate, e duas mensagens sobre o mesmo Pix viram ruido num grupo habitado.

    A idempotencia mora no banco, em dois lugares que se cobrem: a `chave_conteudo` da venda (o
    segundo gesto colide e nao grava) e o `WHERE estado IN ('aberta','confirmada')` da ficha (o
    segundo gesto nao gera evento). Nenhum "quem chegou primeiro" em memoria — nao sobrevive a
    duas entregas concorrentes, que e exatamente quando isso importa.
    """
    promocao = planejar_promocao(
        ficha,
        modelo_id=modelo_id,
        origem_do_gesto=origem_do_gesto,
        dia_do_gesto=dia,
        forma=forma,
        comprovante_da_modelo=comprovante_da_modelo,
    )
    if promocao is None:
        # Ficha sem o valor DELA: nao ha venda de R$ 0,00. A ficha continua aberta e a rotina da
        # manha cobra o que falta (ticket 10) — perguntar o valor agora seria devolver a ela a
        # pergunta que o card existe para nao fazer.
        GRUPO_FINANCEIRO_ANUNCIOS.labels("promocao_sem_valor").inc()
        _logger.info(
            "grupo_financeiro_promocao_sem_valor ficha_id=%s modelo_id=%s mensagem_id=%s",
            ficha.id,
            modelo_id,
            base.mensagem_id,
        )
        return _com_ficha(base, ficha_id=ficha.id, motivo="promocao_sem_valor")

    mensagem_id = _exigir_mensagem(base)
    chave = chave_de_conteudo(
        data=promocao.data,
        valor=promocao.valor,
        modelo_id=modelo_id,
        cliente=promocao.cliente_nome,
    )
    venda = await registrar_venda_da_ficha(
        conn,
        promocao=promocao,
        mensagem_id=mensagem_id,
        chave_conteudo=chave,
        percentual_repasse_snapshot=await percentual_de_repasse(conn, modelo_id),
    )
    realizada = await marcar_ficha_realizada(conn, ficha.id)
    if realizada is not None:
        await registrar_evento_da_ficha(
            conn,
            ficha.id,
            tipo="realizacao",
            # QUEM promoveu, no `campo` do evento (ADR-0046 §5, `gesto.py`). Sem este carimbo a
            # remocao do ✅ nao sabe se pode desfazer a venda: `gesto.AlvoDoGesto.promovida_por`
            # le exatamente esta coluna, e `campo` NULO faria o ✅ nunca conseguir desfazer nem a
            # linha que ele mesmo criou. As duas portas escrevem aqui porque a escrita e uma so.
            campo=PORTA_DA_REACAO if origem_do_gesto == "telefonista" else PORTA_DO_PAGAMENTO,
            valor_anterior=ficha.estado,
            valor_novo="realizada",
            mensagem_id=mensagem_id,
        )

    if venda is None:
        # O mesmo fato ja estava registrado: a outra porta (ADR-0046 §5) chegou antes, ou o
        # atendimento tinha sido anunciado em texto livre. Reconhecer sem falar e sem somar de
        # novo — e a ficha fecha do mesmo jeito, porque o desfecho dela e este.
        GRUPO_FINANCEIRO_ANUNCIOS.labels("ficha_ja_promovida").inc()
        _logger.info(
            "grupo_financeiro_ficha_ja_promovida ficha_id=%s modelo_id=%s chave=%s mensagem_id=%s",
            ficha.id,
            modelo_id,
            chave,
            base.mensagem_id,
        )
        return _com_ficha(base, ficha_id=ficha.id, motivo="ficha_ja_promovida")

    resposta = (
        montar_recibo_da_promocao(
            nome_da_modelo=promocao.nome_da_modelo,
            valor=venda.valor,
            data=venda.data,
            forma=venda.forma_pagamento,
            cliente=venda.cliente_nome,
            duracao_minutos=venda.duracao_minutos,
            local=venda.local_atendimento,
        )
        if falar
        else None
    )
    if resposta is not None:
        await _postar(enviar, resposta, citar=citar)

    GRUPO_FINANCEIRO_ANUNCIOS.labels("ficha_promovida").inc()
    _logger.info(
        "grupo_financeiro_ficha_promovida venda_id=%s ficha_id=%s modelo_id=%s valor=%s data=%s "
        "forma=%s bolso=%s gesto=%s mensagem_id=%s",
        venda.id,
        ficha.id,
        modelo_id,
        venda.valor,
        venda.data,
        promocao.forma_pagamento,
        promocao.bolso,
        origem_do_gesto,
        base.mensagem_id,
    )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=modelo_id,
        mensagem_id=base.mensagem_id,
        # So `vendas`: a venda NASCEU aqui. `pagamentos` e a lista de pendencias de forma que a
        # mensagem RESOLVEU, e esta venda nunca teve uma — ela ja nasceu com a forma dita.
        vendas=(venda.id,),
        pendencias=pendencias_da_venda(venda),
        ficha_id=ficha.id,
        resposta=resposta,
        motivo="ficha_promovida",
    )


async def _ficha_citada(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo_id: UUID,
    modelo_id: UUID,
    abertas: Sequence[FichaDeAgendamento],
) -> UUID | None:
    """Qual ficha a modelo citou ao pagar — inclusive quando ela citou o COMUNICADO (ticket 19).

    Dois saltos, nesta ordem:

    1. **a mensagem citada E a fonte da ficha** — o arranjo sem Grupo de fichas, em que o card
       esta no proprio grupo dela. Uma consulta indexada, e a resposta na maioria dos turnos;
    2. **a mensagem citada e o Comunicado** — a ficha completa foi para o Grupo de fichas e o que
       chegou aqui foi o resumo. Nenhuma coluna liga as duas mensagens (o vinculo do comunicado e
       DERIVADO, `modelo + cliente + valor`), entao o salto e reler o texto citado e casa-lo pela
       MESMA regra de `_comunicado_da_ficha_existente`. Derivar duas vezes pela mesma funcao e o
       que impede os dois caminhos divergirem — um segundo criterio faria o quote resolver para
       uma ficha e o registro do comunicado para outra.

    Custa uma consulta a mais so quando o primeiro salto falha E ha quote, que e o caso raro. As
    fichas ja vem carregadas: o casamento e em memoria, sobre a lista DELA, e por isso nenhum
    quote alcanca ficha de outra modelo.
    """
    if not msg.quoted_message_id:
        return None
    direta = await ficha_aberta_da_mensagem_citada(conn, grupo_id, msg.quoted_message_id)
    if direta is not None:
        return direta
    texto = await texto_da_mensagem_citada(conn, grupo_id, msg.quoted_message_id)
    if not texto:
        return None
    lida = ler_ficha(texto, hoje=msg.dia_brt())
    if lida is None or lida.documento != "comunicado":
        # Ela citou outra coisa (um recibo, uma foto, uma conversa). O alvo continua sendo
        # decidido pelo nome dito e pela lista aberta, como sempre foi.
        return None
    veredito, alvo = casar_comunicado(lida, modelo_id=modelo_id, abertas=abertas)
    if veredito != "vincula" or alvo is None:
        # Sem casar (ou casando com duas), o quote nao aponta nada: quem desempata e a pergunta
        # de sempre, e nao um palpite ancorado num resumo que serve a dois atendimentos.
        return None
    return alvo.id


async def _promover_ficha_da_fala(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    texto: str,
    contexto: Sequence[MensagemRegistrada],
    fichas: Sequence[FichaDeAgendamento],
    forma: FormaPagamento | None,
    venda_escolhida: UUID | None,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """A fala de pagamento fecha uma ficha aberta? `None` = devolve o turno para as vendas.

    A precedencia entre os dois alvos e por FORCA DE SINAL, nao por tipo:

    * ficha apontada por **quote** ou por **nome** vence, mesmo havendo venda aberta — o humano
      disse de qual atendimento fala, e a venda escolhida por "e a unica aberta" e so um palpite
      educado sobre outra coisa;
    * ficha escolhida por **ser a unica** cede a venda apontada: o fato consumado que ja espera a
      forma e o alvo mais provavel de "foi pix", e essa e a conduta que o grupo ja conhece;
    * **ambigua** com varias fichas e nenhuma venda apontada vira UMA pergunta — a mesma do
      desempate de vendas, com o mesmo prefixo, para a tranca contra reperguntar valer para as
      duas.

    Errar aqui nao e uma venda com o campo trocado: e uma venda com o CLIENTE e o VALOR de outro
    atendimento, e a ficha certa continua aberta sendo cobrada.
    """
    if forma is None or not fichas:
        return None

    citada = await _ficha_citada(
        conn, msg, grupo_id=grupo.id, modelo_id=grupo.modelo_id, abertas=fichas
    )
    alvo = escolher_ficha(
        texto=texto,
        # O card do telefonista NAO e alguem apontando para a ficha: ele E a ficha. Deixa-lo no
        # contexto faz o ultimo card postado nomear o proprio cliente e "desempatar" a fala — com
        # tres fichas abertas, "recebi, foi dinheiro" promoveria a do card mais recente em vez de
        # perguntar, criando uma venda com o cliente e o valor de outro atendimento. O contexto
        # inteiro segue valendo para a TRANCA de nao reperguntar (`_ja_perguntou_de_qual_venda`).
        contexto=[m for m in contexto if not parece_ficha_do_telefonista(m.texto)],
        abertas=fichas,
        ficha_citada=citada,
    )

    if alvo.motivo == "escolhida" and alvo.ficha is not None:
        if alvo.sinal == "unica" and venda_escolhida is not None:
            return None
        return await _promover_ficha(
            conn,
            base=base,
            ficha=alvo.ficha,
            modelo_id=grupo.modelo_id,
            forma=forma,
            origem_do_gesto="modelo",
            dia=msg.dia_brt(),
            enviar=enviar,
        )

    if alvo.motivo == "ambigua" and venda_escolhida is None:
        pergunta = (
            montar_pergunta_de_desempate_de_fichas(
                forma=forma, candidatas=fichas, modelo_id=grupo.modelo_id
            )
            if not _ja_perguntou_de_qual_venda(contexto)
            else None
        )
        if pergunta is None:
            return _sem_venda(base, "pagamento_sem_venda_certa")
        await _postar(enviar, pergunta)
        return _sem_venda(base, "promocao_ambigua", resposta=pergunta)

    return None


async def _promover_ficha_do_comprovante(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    valor: Decimal,
    dia: date,
    da_casa: bool,
) -> None:
    """O comprovante fecha a ficha aberta de valor EXATO — antes de a fila do abate ser lida.

    Promovida aqui, a venda entra em `vendas_pix_a_comprovar` e o abate FIFO de sempre a fecha na
    mesma passada: o comprovante vira prova da venda que ele mesmo acabou de fazer nascer, e o
    razao ganha o debito do bruto e o credito da transferencia sem nenhum caminho novo.

    **So valor exato e so uma candidata.** Um Pix que cobre duas fichas (o "600 + 600" real do
    export) nao promove nada e cai no comportamento de hoje — retido com uma pergunta. Casar por
    aproximacao criaria uma venda com o valor de outro atendimento, e ninguem reconfere um numero
    que o sistema preencheu sozinho.

    `da_casa` (destino numa chave conhecida da casa) e a evidencia que decide o BOLSO: comprovante
    dela para a casa e a primeira linha da tabela do ADR-0047 §2 — o dinheiro passou pela conta
    dela. Destino fora da lista nao prova nada, e o bolso fica `nao_dito`, que e estado legitimo.

    Cala sempre: quem fala neste turno e a confirmacao do abate.
    """
    fichas = await fichas_abertas_da_modelo(conn, grupo.modelo_id)
    candidatas = [f for f in fichas if f.valor_de(grupo.modelo_id) == valor]
    if len(candidatas) != 1:
        return
    await _promover_ficha(
        conn,
        base=base,
        ficha=candidatas[0],
        modelo_id=grupo.modelo_id,
        forma="pix",
        origem_do_gesto="modelo",
        dia=dia,
        comprovante_da_modelo=da_casa,
        enviar=None,
        falar=False,
    )


# --- cobranca da agencia: o debito que o gestor posta no grupo ----------------------------------


async def _registrar_cobranca(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    texto: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """A mensagem e uma Cobranca da agencia? Registra o debito e avisa. `None` = nao era.

    Devolver `None` (e nao um `_sem_venda`) e o contrato deste passo da cascata: quase toda
    mensagem do grupo cai aqui e segue adiante para as leituras soltas. So a que traz rubrica
    conhecida E cifra com "R$" (cobranca.py, allowlist fechada) para nesta funcao.

    O recibo sai na hora, como o da venda, e pelo mesmo motivo: quem afirmou o fato foi o humano
    do grupo, e o recibo e a porta de correcao — apagar a mensagem anula a cobranca (ticket 05),
    que e como o grupo desfaz as coisas.

    **Nao ha pergunta minima aqui.** Cobranca sem valor nem chega (`ler_cobranca` devolve `None`),
    e cobranca de modelo que nao e a dona do grupo nao existe: o debito e sempre DELA, porque e o
    grupo dela que a agencia usa para cobrar.
    """
    lida = ler_cobranca(texto)
    if lida is None:
        return None

    data = msg.dia_brt()
    chave = chave_de_conteudo_da_cobranca(
        data=data, valor=lida.valor, modelo_id=grupo.modelo_id, descricao=lida.descricao
    )
    cobranca = await registrar_cobranca(
        conn,
        grupo_id=grupo.id,
        modelo_id=grupo.modelo_id,
        mensagem_id=_exigir_mensagem(base),
        descricao=lida.descricao,
        valor=lida.valor,
        data=data,
        chave_conteudo=chave,
    )
    if cobranca is None:
        # Repost do mesmo debito (ou a mesma cobranca postada nos dois grupos da modelo). O aviso
        # cita a cobranca que VENCEU o dedup, e nao a que acabou de ser lida: e por essa mensagem
        # que o grupo descobre se a chave de conteudo colidiu com o fato errado.
        ja_existente = await cobranca_por_chave_de_conteudo(conn, chave)
        if ja_existente is None:  # pragma: no cover - anulada entre o INSERT e a releitura
            return None
        resposta = montar_aviso_de_cobranca_duplicada(
            descricao=ja_existente.descricao, valor=ja_existente.valor, data=ja_existente.data
        )
        await _postar(enviar, resposta)
        return _sem_venda(base, "cobranca_duplicada", resposta=resposta)

    resposta = montar_recibo_da_cobranca(
        descricao=cobranca.descricao, valor=cobranca.valor, data=cobranca.data
    )
    await _postar(enviar, resposta)

    GRUPO_FINANCEIRO_ANUNCIOS.labels("cobranca_registrada").inc()
    _logger.info(
        "grupo_financeiro_cobranca_registrada cobranca_id=%s modelo_id=%s valor=%s data=%s",
        cobranca.id,
        cobranca.modelo_id,
        cobranca.valor,
        cobranca.data,
    )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=grupo.modelo_id,
        mensagem_id=base.mensagem_id,
        cobrancas=(cobranca.id,),
        resposta=resposta,
        motivo="cobranca_registrada",
    )


# --- vale: o adiantamento que o gestor declara no grupo (ticket 15) ------------------------------
#
# O vale entra por DUAS portas (ADR-0045 §8): o painel, que e a canonica e tem `created_by`, e esta
# fala, que e a conveniente. Ela existe porque o adiantamento e dito no grupo o tempo todo
# ("adiantei 500 pra ela") e obrigar o gestor a abrir a tela toda vez e a diferenca entre o saldo
# estar certo e estar mais ou menos certo.
#
# Nada aqui reimplementa razao: `registrar_lancamento_manual` grava a linha com `origem='grupo'` e
# `mensagem_id` (o CHECK do banco exige o par), e `razao.apurar` ja sabe que vale e debito dela. A
# ORIGEM sobrevive na coluna de proposito — e por ela que o extrato do painel distingue o vale que
# o gestor digitou do que o agente leu numa conversa, e so um dos dois tem alguem do lado de ca
# responsavel pelo numero.


async def _registrar_vale(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    texto: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """A mensagem declara um Vale? Lanca o debito e emite o recibo. `None` = nao era.

    Devolver `None` (e nao um `_sem_venda`) e o contrato deste passo da cascata: quase toda
    mensagem do grupo passa por aqui e segue adiante. So a que traz marcador de emprestimo da
    allowlist fechada para nesta funcao — e "ficou com ela", dito sobre uma venda, nunca para
    (ADR-0047 §5: aquilo e bolso mais ausencia de transferencia, e lancar vale contaria o mesmo
    dinheiro duas vezes).

    **Confianca baixa NAO lanca.** A leitura hesitante — adiantamento sem valor, ou com dois
    valores na mesma frase — vira a pergunta minima que o modulo ja tem, e a resposta e absorvida
    depois (`_completar_vale_pendente`). Escrever um palpite aqui e dinheiro que ninguem confere:
    o vale sai do saldo dela no fechamento e nao deixa nenhum outro rastro para conferir contra.

    O vale e sempre DA DONA do grupo, como a cobranca: nao ha "de quem?" a resolver, porque vale
    de outra pessoa nao existe no grupo dela.
    """
    lida = ler_vale(texto)
    if lida is None:
        return None
    if isinstance(lida, ValeHesitante):
        pergunta = montar_pergunta_do_vale(lida)
        await _postar(enviar, pergunta)
        return _sem_venda(base, "vale_incompleto", resposta=pergunta)

    return await _lancar_vale(
        conn,
        base=base,
        modelo_id=grupo.modelo_id,
        valor=lida.valor,
        data=msg.dia_brt(),
        descricao=lida.descricao,
        mensagem_id=_exigir_mensagem(base),
        enviar=enviar,
    )


async def _lancar_vale(
    conn: AsyncConnection[Any],
    *,
    base: ResultadoDaPorta,
    modelo_id: UUID,
    valor: Decimal,
    data: date,
    descricao: str,
    mensagem_id: UUID,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """A escrita do vale, comum as duas entradas: a fala completa e a resposta a pergunta.

    Uma escrita so para os dois caminhos pelo mesmo motivo do `_executar_plano` da venda: dedup,
    recibo e log tem que ser identicos, senao o vale que nasceu de "adiantei 500 pra ela" e o que
    nasceu de "adiantei pra ela" + "500" viram dois fatos com condutas diferentes.
    """
    chave = chave_de_conteudo_do_vale(
        data=data, valor=valor, modelo_id=modelo_id, descricao=descricao
    )
    lancamento = await registrar_lancamento_manual(
        conn,
        modelo_id=modelo_id,
        tipo="vale",
        sentido="debito",
        valor=valor,
        data=data,
        origem="grupo",
        descricao=descricao,
        mensagem_id=mensagem_id,
        chave_conteudo=chave,
    )
    if lancamento is None:
        # Repost da mesma fala (ou a mesma fala nos dois grupos da modelo). O aviso cita o vale
        # que VENCEU o dedup, e nao o que acabou de ser lido: e por essa mensagem que o grupo
        # descobre se a chave de conteudo colidiu com o fato errado.
        ja_existente = await lancamento_manual_por_chave_de_conteudo(conn, chave)
        if ja_existente is None:  # pragma: no cover - anulado entre o INSERT e a releitura
            return _sem_venda(base, "vale_duplicado")
        resposta = montar_aviso_de_vale_duplicado(valor=ja_existente.valor, data=ja_existente.data)
        await _postar(enviar, resposta)
        return _sem_venda(base, "vale_duplicado", resposta=resposta)

    resposta = montar_recibo_do_vale(valor=lancamento.valor, data=lancamento.data)
    await _postar(enviar, resposta)

    GRUPO_FINANCEIRO_ANUNCIOS.labels("vale_registrado").inc()
    _logger.info(
        "grupo_financeiro_vale_registrado vale_id=%s modelo_id=%s valor=%s data=%s origem=grupo",
        lancamento.id,
        lancamento.modelo_id,
        lancamento.valor,
        lancamento.data,
    )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=modelo_id,
        mensagem_id=base.mensagem_id,
        vales=(lancamento.id,),
        resposta=resposta,
        motivo="vale_registrado",
    )


async def _corrigir_vale_por_quote(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    texto: str,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """A mensagem responde o recibo do vale corrigindo o numero? `None` = nao e correcao de vale.

    A leitura da correcao e a MESMA da venda (`ler_correcao`), de proposito: "foi 600" e "na
    verdade foi dia 18" sao a mesma frase nos dois eixos, e duas gramaticas para a mesma frase
    seriam duas condutas divergentes. So os campos que um vale TEM sao aceitos — valor e data;
    cliente, duracao e forma de pagamento nao existem num adiantamento, e uma correcao que fala
    deles esta falando de outra coisa.

    Le o texto ANTES de ir ao banco: a consulta so acontece quando a frase ja e uma correcao, e
    nao a cada quote do grupo (que e o gesto mais comum que existe ali).
    """
    if not msg.quoted_message_id:
        return None
    correcao = ler_correcao(texto, referencia=msg.dia_brt())
    if correcao is None:
        return None
    campos = correcao.campos()
    if not campos or any(campo not in _CAMPOS_DO_VALE for campo in campos):
        return None

    alvos = await lancamentos_manuais_da_mensagem_citada(conn, grupo.id, msg.quoted_message_id)
    vale = next((linha for linha in alvos if linha.tipo == "vale"), None)
    if vale is None:
        return None

    valor = correcao.valor if correcao.valor is not None else vale.valor
    data = correcao.data or vale.data
    mudancas = _mudancas_do_vale(vale, valor=valor, data=data)
    if not mudancas:
        # "foi 500" num vale que ja esta em 500. Calado de proposito, como na venda: nao houve
        # evento, e responder "corrigi" a uma correcao que nao corrigiu nada e pior que o silencio.
        return _sem_venda(base, "vale_correcao_sem_efeito")

    corrigido = await corrigir_lancamento_manual(
        conn,
        vale.id,
        valor=valor,
        data=data,
        # A chave segue o FATO, como na venda: sem recalcular, o dedup continuaria vigiando o vale
        # de R$ 500,00 que nao existe mais, e o repost da fala ja corrigida nasceria como um
        # segundo debito vivo.
        chave_conteudo=chave_de_conteudo_do_vale(
            data=data,
            valor=valor,
            modelo_id=vale.modelo_id,
            descricao=vale.descricao or DESCRICAO_PADRAO_DO_VALE,
        ),
    )
    if corrigido is None:
        await _postar(enviar, AVISO_DE_CORRECAO_DUPLICADA)
        return _sem_venda(base, "vale_correcao_duplicada", resposta=AVISO_DE_CORRECAO_DUPLICADA)

    eco = montar_eco_de_correcao(mudancas)
    await _postar(enviar, eco)
    GRUPO_FINANCEIRO_ANUNCIOS.labels("vale_corrigido").inc()
    _logger.info(
        "grupo_financeiro_vale_corrigido vale_id=%s campos=%s mensagem_id=%s",
        corrigido.id,
        [m.campo for m in mudancas],
        base.mensagem_id,
    )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=corrigido.modelo_id,
        mensagem_id=base.mensagem_id,
        vales_corrigidos=(corrigido.id,),
        resposta=eco,
        motivo="vale_corrigido",
    )


_CAMPOS_DO_VALE: tuple[CampoCorrigivel, ...] = ("valor", "data")
"""O que um adiantamento tem e o que, portanto, a correcao por quote pode trocar nele.

`tipo`, `sentido` e `origem` ficam de fora e nao por esquecimento: eles sao a identidade do
lancamento, e trocar qualquer um por uma frase no grupo viraria um vale em ajuste — ou um debito
em credito — sem ninguem conferir."""


def _mudancas_do_vale(vale: LancamentoManual, *, valor: Decimal, data: date) -> tuple[Mudanca, ...]:
    """O que REALMENTE muda no vale — vazio quando a correcao repetiu o que ja era.

    Compara os dois estados em vez de confiar no que a mensagem disse, pela mesma razao de
    `mudancas_entre`: o eco e o rastro so sao honestos se sairem da diferenca real.
    """
    mudancas: list[Mudanca] = []
    if vale.valor != valor:
        mudancas.append(Mudanca("valor", formatar_reais(vale.valor), formatar_reais(valor)))
    if vale.data != data:
        mudancas.append(Mudanca("data", f"{vale.data:%d/%m}", f"{data:%d/%m}"))
    return tuple(mudancas)


# --- resposta solta: forma de pagamento, ou o que faltava ao anuncio ----------------------------


async def _absorver_resposta(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    texto: str,
    extrair: ExtratorDeAnuncio,
    enviar: EnviarNoGrupo | None,
    ler_intencao: LerIntencao | None = None,
) -> ResultadoDaPorta:
    """Mensagem que nao e anuncio: ainda pode ser a peca que faltava a uma venda.

    A triagem de custo continua valendo — conversa comprida sai daqui sem tocar o banco. Mensagem
    CURTA custa uma releitura do log do grupo (uma consulta indexada, nao extracao): e o preco de
    entender "600" e "Sim", que e o que o grupo real responde.
    """
    # O dado cadastral vem PRIMEIRO entre as leituras soltas, e nao por precedencia de valor: e
    # que "Torre 2 Apt 2706" tem numero, e todo leitor daqui para baixo procura numero. Lido
    # aqui, o apartamento nao chega perto de virar o valor de um anuncio incompleto.
    cadastral = await _atualizar_cadastro(conn, msg, grupo=grupo, base=base, texto=texto)
    if cadastral is not None:
        return cadastral

    fala = ler_fala_de_pagamento(texto)
    if fala is None and not _vale_ler(texto, com_llm=ler_intencao is not None):
        return _sem_venda(base, "nao_e_anuncio")

    # As vendas abertas do grupo entram AQUI, e nao la dentro, porque elas sao insumo das duas
    # coisas: de QUEM recebe a forma e de COMO a fala e lida. A cobranca da manha nomeia N vendas
    # e a resposta humana a uma lista nomeia de qual se fala ("o do Gabriel foi pix") — nome
    # proprio nao passa pela allowlist a menos que seja cliente de venda aberta. Custa uma
    # consulta indexada, e so para mensagem curta, no mesmo orcamento da releitura do log.
    abertas = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)
    # As FICHAS abertas entram pelo mesmo motivo das vendas, e no mesmo orcamento (uma consulta
    # indexada, so para mensagem curta): a partir do ADR-0044 a mesma fala tem dois alvos
    # possiveis, e o cliente da ficha precisa estar na allowlist pelo mesmo motivo que o da venda
    # — "o do Igor foi dinheiro" e a resposta humana a uma lista, e sem o nome permitido a fala
    # inteira e descartada em silencio. A lista e a da MODELO, nao a do grupo (ADR-0046 §2).
    fichas = await fichas_abertas_da_modelo(conn, grupo.modelo_id)
    if fala is None:
        fala = ler_fala_de_pagamento(
            texto,
            nomes_de_cliente=[
                nome
                for nome in ([v.cliente_nome for v in abertas] + [f.cliente_nome for f in fichas])
                if nome
            ],
        )
    if fala is not None and fala.tipo == "pergunta":
        # Um gestor perguntando "Foi pix ou din ?". O agente nao responde por ninguem — mas a
        # pergunta fica no log, e e dela que o "Sim" seguinte herda a forma.
        return _sem_venda(base, "pergunta_de_pagamento")

    contexto = await _contexto_do_grupo(conn, msg, grupo_id=grupo.id, base=base)

    if ler_intencao is not None:
        # A LLM le PRIMEIRO, e a allowlist fica de rede: ela e que tem cauda. O grupo escreve "foi
        # tudo no pix menos o do Igor" e nenhuma lista de palavras permitidas vai cobrir isso —
        # cada fraseado novo era uma rodada de manutencao, e enquanto ela nao chegava a mensagem
        # caia no chao em silencio (a fila nao andava e a cobranca da manha voltava identica).
        #
        # Le TAMBEM com a fila vazia. A versao anterior pulava o provider quando nao havia venda
        # aberta ("sem alvo para apontar, nao ha o que a leitura mude") e isso ficou falso quando o
        # pedido de fechamento entrou aqui: no replay, "Como tá a conta amiga?" caiu no silencio
        # justamente no melhor momento para perguntar — logo depois de tudo ter sido quitado. O
        # teto de custo continua sendo `_vale_ler`, que ja barra conversa comprida.
        intencao = await ler_intencao(texto, abertas, contexto)
        # A LLM so ASSUME o turno quando traz o que a allowlist nao tem: um alvo, com confianca.
        # Sem isso — lista vazia ou leitura hesitante — quem decide e a allowlist, que sabe uma
        # coisa que o modelo nao tem como saber olhando so o texto: que aquele "Pix" seco responde
        # a pergunta que a gestora fez logo depois de UM anuncio, e e daquela venda. E o gesto mais
        # comum do grupo real (o export de 08/08 e 12/08 tem tres), e nele a pergunta de desempate
        # ("foi pix em qual?") seria o agente devolvendo a pergunta que acabou de ser respondida.
        #
        # A ordem inversa (LLM sempre na frente) foi medida no replay e piorou o export real: com a
        # leitura hesitante mandando, "Dinheiro" caiu na venda errada e "Sim" virou pergunta.
        aponta_com_confianca = intencao is not None and bool(intencao.vendas) and intencao.confiavel
        if (
            intencao is not None
            and intencao.tipo == "forma_de_pagamento"
            and (aponta_com_confianca or fala is None)
        ):
            return await _absorver_intencao(
                conn,
                msg,
                grupo=grupo,
                base=base,
                intencao=intencao,
                texto=texto,
                abertas=abertas,
                fichas=fichas,
                contexto=contexto,
                enviar=enviar,
            )
        if intencao is not None and intencao.tipo == "pedido_de_fechamento":
            # O mesmo pedido que a allowlist de `e_pedido_de_fechamento` ja tentou la em cima e
            # nao reconheceu: "como tá a conta amiga?" nao tem nenhuma das palavras-gatilho, e
            # ficava em silencio depois de a LLM ter entendido — o pior dos dois mundos, porque a
            # casa pagou a leitura e jogou fora. Aqui nao ha risco de escrita: o extrato so LE.
            return await _fechar(conn, grupo=grupo, base=base, enviar=enviar)
        if intencao is not None and intencao.tipo == "anulacao_de_venda":
            return await _anular_por_texto(
                conn, base=base, intencao=intencao, abertas=abertas, enviar=enviar
            )

    if fala is not None:
        absorvido = await _absorver_pagamento(
            conn,
            msg,
            grupo=grupo,
            base=base,
            fala=fala,
            texto=texto,
            abertas=abertas,
            fichas=fichas,
            contexto=contexto,
            enviar=enviar,
        )
        if absorvido is not None:
            return absorvido

    # A resposta a pergunta do VALE vem antes da resposta a pergunta do anuncio, e o criterio nao
    # e precedencia de eixo: e QUAL pergunta o agente fez por ultimo. `_completar_vale_pendente`
    # so assume o turno quando a pergunta mais recente dele no log foi a do adiantamento — se foi
    # a do anuncio, ele devolve `None` na hora e o caminho de sempre segue. Sem isso, o "500" que
    # responde "quanto foi o adiantamento?" cairia no leitor de valor avulso e o adiantamento
    # viraria RECEITA de uma venda incompleta, que e o erro mais caro que este ticket podia criar.
    vale = await _completar_vale_pendente(
        conn,
        grupo=grupo,
        base=base,
        texto=texto,
        agora=msg.recebida_em,
        contexto=contexto,
        enviar=enviar,
    )
    if vale is not None:
        return vale

    completado = await _completar_anuncio_pendente(
        conn,
        base=base,
        texto=texto,
        agora=msg.recebida_em,
        contexto=contexto,
        extrair=extrair,
        enviar=enviar,
    )
    return completado if completado is not None else _sem_venda(base, "nao_e_anuncio")


async def _completar_vale_pendente(
    conn: AsyncConnection[Any],
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    texto: str,
    agora: datetime,
    contexto: Sequence[MensagemRegistrada],
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """Esta mensagem responde a pergunta do vale? Entao o adiantamento nasce agora. `None` = nao.

    A guarda e a mesma do anuncio, e a mesma da conversa humana: so a ULTIMA pergunta do agente
    pode estar esperando. Se ele perguntou pelo vale e depois perguntou pelo valor de um anuncio,
    a pergunta do vale morreu — e um "500" que chega agora e do anuncio, nao do adiantamento.

    A data e a do dia em que o vale foi DECLARADO (a mensagem da pergunta), e nao a da resposta:
    o adiantamento aconteceu quando o gestor disse que aconteceu, e datar pela resposta jogaria
    para o dia seguinte todo vale respondido de manha. E a mesma disciplina do anuncio, que nasce
    datado do anuncio e nao do "600" que o completou.

    A descricao vem da FALA original, recuperada do log: sem ela o vale ficaria no painel como uma
    linha anonima ao lado da origem `grupo`, e ninguem saberia de onde veio o debito.
    """
    achado = ler_valor_avulso(texto)
    if achado is None:
        return None

    pergunta = next(
        (m for m in contexto if m.de_mim and m.texto.startswith(PREFIXO_DA_PERGUNTA)), None
    )
    if pergunta is None or not e_pergunta_do_vale(pergunta.texto):
        return None
    if pergunta.recebida_em < agora - JANELA_DA_PERGUNTA_MINIMA:
        return None

    valor, _ = achado
    declaracao = next(
        (
            m
            for m in contexto
            if not m.de_mim
            and m.recebida_em <= pergunta.recebida_em
            and isinstance(ler_vale(m.texto), ValeHesitante)
        ),
        None,
    )
    lida = ler_vale(declaracao.texto) if declaracao is not None else None
    descricao = lida.descricao if isinstance(lida, ValeHesitante) else DESCRICAO_PADRAO_DO_VALE

    return await _lancar_vale(
        conn,
        base=base,
        modelo_id=grupo.modelo_id,
        valor=valor,
        data=pergunta.dia(),
        descricao=descricao,
        # A mensagem-fonte e a que RESPONDEU, e nao a que perguntou: a fonte de um lancamento e a
        # ultima mensagem HUMANA que o afirmou, e e ela que a delecao alcanca. A pergunta e fala
        # do agente — apaga-la nao pode desfazer debito nenhum.
        mensagem_id=_exigir_mensagem(base),
        enviar=enviar,
    )


async def _atualizar_cadastro(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    texto: str,
) -> ResultadoDaPorta | None:
    """Guarda o dado operacional que passou pelo grupo. `None` = nao havia dado nenhum.

    **Sem `enviar` no corpo, de proposito**: nao ha caminho daqui ate uma fala. O agente atualiza
    os Dados cadastrais de forma oportunista e CALADA (docs/dominio, "Agente financeiro") — nem
    recibo, nem "anotei", e muito menos a pergunta que o dominio proibe ("qual seu apartamento?").
    A gestora ja perguntou; o agente so estava ouvindo.

    O que ele diz sobre o que aprendeu vai para o `motivo` e para o log, que e onde quem opera
    procura — e nunca para o grupo, que e onde a modelo trabalha.
    """
    leitura = ler_dado_cadastral(
        texto, autor_e_a_modelo=autor_e_a_modelo(msg.autor_jid, grupo.numero_modelo)
    )
    if leitura.veredito == "nada":
        return None
    if leitura.veredito == "de_terceiro" or leitura.dado is None:
        # Chave Pix ditada por quem nao e a dona do grupo (o "Minha Chave Pix para transferência:"
        # real, que era de um gestor passando a conta da casa). Para AQUI em vez de devolver o
        # turno: a mensagem tem um numero comprido dentro, e o unico destino que sobraria para ela
        # seria algum leitor de valor.
        _logger.info(
            "grupo_financeiro_cadastro_de_terceiro grupo_id=%s autor=%s mensagem_id=%s",
            grupo.id,
            msg.autor_jid,
            base.mensagem_id,
        )
        return _sem_venda(base, "cadastro_de_terceiro")

    registrado = await registrar_dado_cadastral(
        conn,
        modelo_id=grupo.modelo_id,
        campo=leitura.dado.campo,
        valor=leitura.dado.valor,
        mensagem_id=_exigir_mensagem(base),
        observado_em=msg.recebida_em,
    )
    if registrado is None:
        # Repetiu o que ja estava guardado. Sem linha nova: observacao que nao muda nada viraria
        # um evento de auditoria com o mesmo valor dos dois lados, e o historico deixaria de ser
        # a lista das vezes em que o dado MUDOU.
        return _sem_venda(base, "cadastro_sem_efeito")

    GRUPO_FINANCEIRO_ANUNCIOS.labels("cadastro_atualizado").inc()
    # Sem o VALOR no log, sempre: chave Pix e dado de pagamento e endereco e onde ela mora e
    # trabalha. O que se precisa saber operando e que o campo mudou e por causa de qual mensagem —
    # o dado em si esta no painel, atras de autenticacao.
    _logger.info(
        "grupo_financeiro_cadastro_atualizado modelo_id=%s campo=%s tinha_valor=%s mensagem_id=%s",
        grupo.modelo_id,
        registrado.campo,
        registrado.valor_anterior is not None,
        base.mensagem_id,
    )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=grupo.modelo_id,
        mensagem_id=base.mensagem_id,
        cadastro=registrado,
        motivo="cadastro_atualizado",
    )


async def _absorver_pagamento(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    fala: FalaDePagamento,
    texto: str,
    abertas: Sequence[VendaRegistrada],
    fichas: Sequence[FichaDeAgendamento],
    contexto: Sequence[MensagemRegistrada],
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """Liga a forma dita a UMA venda aberta — ou faz a Ficha de agendamento virar venda.

    Dois alvos desde o ADR-0044: a venda que ja existe e espera a forma, e a ficha que ainda nao
    virou dinheiro. Quem decide entre eles e `_promover_ficha_da_fala`, e ele so entra depois de a
    escolha da VENDA estar feita — e a escolha da venda que diz se ha um alvo consumado
    disputando a mesma frase.
    """
    citada: UUID | None = None
    if msg.quoted_message_id:
        citada = await venda_aberta_da_mensagem_citada(conn, grupo.id, msg.quoted_message_id)

    escolha = escolher_pagamento(
        fala=fala, texto=texto, contexto=contexto, abertas=abertas, venda_citada=citada
    )
    if escolha.motivo == "sem_forma":
        # "Sim" que nao responde pergunta de pagamento nenhuma — o grupo diz isso o dia inteiro
        # ("Ficou com você" -> "Sim"). Devolve o turno para as outras leituras.
        return None
    if escolha.motivo == "todas" and escolha.forma is not None:
        return await _absorver_pagamento_de_todas(
            conn, base=base, forma=escolha.forma, vendas=escolha.vendas, enviar=enviar
        )

    # A FICHA entra aqui: depois do coletivo (que e afirmacao sobre escopo e nao tem nada a ver
    # com combinado nenhum) e antes da escrita na venda, porque so ela sabe distinguir "recebi,
    # foi dinheiro" sobre o card do Igor de uma resposta a pendencia de outro atendimento.
    promovida = await _promover_ficha_da_fala(
        conn,
        msg,
        grupo=grupo,
        base=base,
        texto=texto,
        contexto=contexto,
        fichas=fichas,
        forma=escolha.forma,
        venda_escolhida=escolha.venda_id,
        enviar=enviar,
    )
    if promovida is not None:
        return promovida

    if escolha.venda_id is None or escolha.forma is None:
        # Falou de pagamento, mas nao da para saber de qual venda. Adivinhar segue proibido —
        # marcar a venda errada some do fechamento e nunca mais e cobrada. Havendo candidata,
        # porem, a conduta nao e o silencio: e devolver a pergunta que aproveita a forma ja dita.
        pergunta = (
            montar_pergunta_de_desempate(forma=escolha.forma, candidatas=abertas)
            if escolha.motivo == "ambigua"
            and escolha.forma is not None
            and not _ja_perguntou_de_qual_venda(contexto)
            else None
        )
        if pergunta is None:
            return _sem_venda(base, "pagamento_sem_venda_certa")
        await _postar(enviar, pergunta)
        return _sem_venda(base, "pagamento_ambiguo", resposta=pergunta)

    return await _absorver_pagamento_de_uma(
        conn, base=base, venda_id=escolha.venda_id, forma=escolha.forma, enviar=enviar
    )


async def _absorver_pagamento_de_uma(
    conn: AsyncConnection[Any],
    *,
    base: ResultadoDaPorta,
    venda_id: UUID,
    forma: FormaPagamento,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """Escreve a forma em UMA venda e devolve o recibo nomeado.

    Extraido para ser o mesmo caminho dos dois leitores (allowlist e LLM): a conduta que o grupo
    ve — o recibo com cliente, valor e dia — nao pode depender de quem interpretou a frase.
    """
    venda = await definir_forma_de_pagamento(
        conn, venda_id, forma=forma, mensagem_id=_exigir_mensagem(base)
    )
    if venda is None:  # pragma: no cover - corrida: outra entrega resolveu a mesma pendencia
        return _sem_venda(base, "pagamento_sem_venda_certa")
    assert venda.forma_pagamento is not None  # acabou de ser escrita pelo UPDATE

    recibo = montar_recibo_de_pagamento(
        forma=venda.forma_pagamento,
        valor=venda.valor,
        data=venda.data,
        cliente=venda.cliente_nome,
    )
    GRUPO_FINANCEIRO_ANUNCIOS.labels("pagamento_absorvido").inc()
    _logger.info(
        "grupo_financeiro_pagamento_absorvido venda_id=%s forma=%s mensagem_id=%s",
        venda.id,
        venda.forma_pagamento,
        base.mensagem_id,
    )
    await _postar(enviar, recibo)
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=venda.modelo_id,
        mensagem_id=base.mensagem_id,
        pagamentos=(venda.id,),
        pendencias=pendencias_da_venda(venda),
        resposta=recibo,
        motivo="pagamento_absorvido",
    )


async def _anular_por_texto(
    conn: AsyncConnection[Any],
    *,
    base: ResultadoDaPorta,
    intencao: IntencaoDoGrupo,
    abertas: Sequence[VendaRegistrada],
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """ "cancela esse atendimento do denis, ele nao veio" — a venda que nao aconteceu, dita em fala.

    Ate aqui esse gesto morria calado e a modelo era cobrada na manha seguinte por um atendimento
    que nao houve. O caminho suportado era apagar a mensagem do anuncio (o que o grupo ja faz), e
    esta porta faz exatamente o MESMO efeito — anula a venda e registra o evento — a partir da
    outra superficie. Duas superficies com efeitos diferentes seria pior que uma so.

    Tres trancas, e sao as mesmas do resto do modulo:

    * **UMA venda por vez**, apontada por indice da lista que a porta ofereceu. Cancelar em lote
      por fala livre nao tem gesto real que o justifique e apagaria dinheiro no escuro.
    * **Confianca baixa nao apaga** — vira a pergunta de qual, que e barata.
    * So entra na lista quem esta **sem forma de pagamento dita**: uma venda ja fechada em pix ou
      dinheiro nao se cancela por uma frase no meio da conversa.
    """
    alvos = intencao.vendas if intencao.confiavel else ()
    if len(alvos) != 1:
        if not abertas:
            return _sem_venda(base, "nao_e_anuncio")
        pergunta = montar_pergunta_de_anulacao([(v.cliente_nome, v.valor) for v in abertas])
        await _postar(enviar, pergunta)
        return _sem_venda(base, "anulacao_ambigua", resposta=pergunta)

    alvo = alvos[0]
    anulada = await anular_venda(conn, alvo.id)
    if anulada is None:  # pragma: no cover - a venda ja tinha morrido (delecao concorrente)
        return _sem_venda(base, "nao_e_anuncio")
    await registrar_eventos_da_venda(
        conn, anulada.id, tipo="anulacao", mensagem_id=_exigir_mensagem(base)
    )
    GRUPO_FINANCEIRO_ANUNCIOS.labels("venda_anulada").inc()
    _logger.info(
        "grupo_financeiro_venda_anulada_por_texto venda_id=%s modelo_id=%s valor=%s mensagem_id=%s",
        anulada.id,
        anulada.modelo_id,
        anulada.valor,
        base.mensagem_id,
    )
    resposta = montar_recibo_de_anulacao(
        valor=anulada.valor,
        data=anulada.data,
        cliente=anulada.cliente_nome,
        tinha_comprovante=anulada.comprovante_id is not None,
    )
    await _postar(enviar, resposta)
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=anulada.modelo_id,
        mensagem_id=base.mensagem_id,
        anuladas=(anulada.id,),
        resposta=resposta,
        motivo="venda_anulada",
    )


async def _absorver_intencao(
    conn: AsyncConnection[Any],
    msg: MensagemDoGrupo,
    *,
    grupo: GrupoFinanceiro,
    base: ResultadoDaPorta,
    intencao: IntencaoDoGrupo,
    texto: str,
    abertas: Sequence[VendaRegistrada],
    fichas: Sequence[FichaDeAgendamento],
    contexto: Sequence[MensagemRegistrada],
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """A leitura da LLM virando conduta. Ela LE; quem decide o que fazer continua sendo daqui.

    A escada e a mesma de sempre, e e essa continuidade que faz a troca de leitor ser segura: um
    alvo vira recibo nomeado, N alvos viram recibo coletivo, nenhum alvo vira a pergunta de
    desempate. O que mudou foi so quem responde "de qual venda ela esta falando".

    Confianca baixa NAO escreve. O modelo diz quando esta interpretando, e interpretar sobre
    dinheiro e exatamente o caso em que perguntar custa uma mensagem e errar custa uma venda que
    some da conferencia para sempre. A pergunta aproveita a forma ja dita, entao o turno nao se
    perde.

    Quem chega aqui ja passou pelo filtro do chamador: ou a leitura aponta alvo com confianca, ou
    a allowlist nao tinha nada a dizer sobre a frase. A pergunta de desempate deste corpo e, por
    isso, o ULTIMO recurso — e nao a resposta padrao para toda leitura hesitante.
    """
    if intencao.forma is None:  # pragma: no cover - o leitor ja normaliza isto
        return _sem_venda(base, "nao_e_anuncio")

    alvos = intencao.vendas if intencao.confiavel else ()
    if not alvos:
        # A FICHA antes da pergunta, e so quando a LLM nao apontou venda nenhuma: o leitor por
        # indice enxerga a lista de VENDAS abertas (`leitura.py`), entao "recebi tudo certinho" com
        # a fila vazia chega aqui sem alvo — e o alvo existe, so que e um combinado. Sem este
        # desvio, a fala que a LLM entendeu morreria em "nao sei de qual venda" enquanto a ficha do
        # Igor seguia aberta. Ensinar a LLM a apontar ficha por indice e o ticket 19.
        promovida = await _promover_ficha_da_fala(
            conn,
            msg,
            grupo=grupo,
            base=base,
            texto=texto,
            contexto=contexto,
            fichas=fichas,
            forma=intencao.forma,
            venda_escolhida=None,
            enviar=enviar,
        )
        if promovida is not None:
            return promovida
        pergunta = (
            montar_pergunta_de_desempate(forma=intencao.forma, candidatas=abertas)
            if not _ja_perguntou_de_qual_venda(contexto)
            else None
        )
        if pergunta is None:
            return _sem_venda(base, "pagamento_sem_venda_certa")
        await _postar(enviar, pergunta)
        return _sem_venda(base, "pagamento_ambiguo", resposta=pergunta)

    if len(alvos) == 1:
        return await _absorver_pagamento_de_uma(
            conn, base=base, venda_id=alvos[0].id, forma=intencao.forma, enviar=enviar
        )
    return await _absorver_pagamento_de_todas(
        conn,
        base=base,
        forma=intencao.forma,
        vendas=tuple(v.id for v in alvos),
        enviar=enviar,
    )


async def _absorver_pagamento_de_todas(
    conn: AsyncConnection[Any],
    *,
    base: ResultadoDaPorta,
    forma: FormaPagamento,
    vendas: Sequence[UUID],
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """ "Todos foram pix": UMA resposta fecha N pendencias de forma.

    E a resposta natural a cobranca da manha, que e consolidada por regra do dominio — ela lista
    quatro vendas numa mensagem, e ninguem responde a uma lista com quatro mensagens. Ate 14/08 o
    grupo respondia e nada acontecia: "todos foram pix" era descartado em silencio e "tudo pix" era
    lido como resposta singular, com o agente devolvendo "foi pix em qual?" logo depois de ele ter
    dito "em todas". A fila nao andava, e a mesma cobranca voltava identica no dia seguinte.

    Escrita larga com recibo largo: o recibo diz **quantas** vendas, **quais** (ate tres nomes) e o
    **total**, que sao os tres numeros com que o gestor confere se o "todos" dele bateu com o do
    agente. Uma venda anunciada depois da cobranca entra nesta conta, e e por isso que o total
    precisa aparecer.
    """
    escritas: list[VendaRegistrada] = []
    for venda_id in vendas:
        venda = await definir_forma_de_pagamento(
            conn, venda_id, forma=forma, mensagem_id=_exigir_mensagem(base)
        )
        if venda is not None:
            escritas.append(venda)
    if not escritas:  # pragma: no cover - corrida: outra entrega resolveu as mesmas pendencias
        return _sem_venda(base, "pagamento_sem_venda_certa")

    recibo = montar_recibo_de_pagamento_coletivo(
        forma=forma,
        vendas=[(v.cliente_nome, v.valor) for v in escritas],
        total=sum((v.valor for v in escritas), Decimal("0.00")),
    )
    GRUPO_FINANCEIRO_ANUNCIOS.labels("pagamento_coletivo").inc()
    _logger.info(
        "grupo_financeiro_pagamento_coletivo vendas=%s forma=%s mensagem_id=%s",
        len(escritas),
        forma,
        base.mensagem_id,
    )
    await _postar(enviar, recibo)
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=escritas[0].modelo_id,
        mensagem_id=base.mensagem_id,
        pagamentos=tuple(v.id for v in escritas),
        pendencias=tuple(p for venda in escritas for p in pendencias_da_venda(venda)),
        resposta=recibo,
        motivo="pagamento_coletivo",
    )


async def _completar_anuncio_pendente(
    conn: AsyncConnection[Any],
    *,
    base: ResultadoDaPorta,
    texto: str,
    agora: datetime,
    contexto: Sequence[MensagemRegistrada],
    extrair: ExtratorDeAnuncio,
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta | None:
    """Esta mensagem e a resposta a pergunta minima? Entao a venda nasce agora, datada do anuncio.

    So o ULTIMO anuncio do grupo pode estar esperando. E a mesma regra da conversa humana (se
    veio anuncio novo depois, a pergunta velha morreu) e ela fecha o buraco de um anuncio
    incompleto antigo capturar um numero solto meses depois.
    """
    anuncio_msg = next(
        (m for m in contexto if not m.de_mim and parece_anuncio_de_venda(m.texto)), None
    )
    if anuncio_msg is None:
        return None
    if anuncio_msg.recebida_em < agora - JANELA_DA_PERGUNTA_MINIMA:
        return None

    anuncio = extrair(anuncio_msg.texto)
    cadastro = await carregar_cadastro_de_nomes(conn)
    plano = planejar(anuncio, cadastro=cadastro, dona_do_grupo=base.modelo_id)
    if plano.participante_oculta:
        return None
    if plano.ambiguo or not plano.faltas:
        # Nada estava esperando resposta: ou o anuncio ja rendeu tudo que podia render, ou o que
        # falta nele e homonimo de cadastro, que resposta nenhuma no grupo resolve. Registrar
        # agora seria inventar um destravamento que ninguem pediu.
        return None

    if "valor" in plano.faltas:
        achado = ler_valor_avulso(texto)
        if achado is None:
            return None
        valor, minutos = achado
        anuncio = replace(
            anuncio,
            valor=anuncio.valor if plano.por_modelo else valor,
            valor_por_modelo=valor if plano.por_modelo else anuncio.valor_por_modelo,
            duracao_minutos=anuncio.duracao_minutos or minutos,
        )

    if "modelo" in plano.faltas:
        # "“Alicia / fran loira” é quem?" -> "é a Duda". A resposta ENSINA: os nomes perguntados
        # viram Nome de anuncio da mulher que ela nomeou, e a partir daqui o resolver acha
        # sozinho — e por isso que o mesmo nome nunca precisa ser perguntado duas vezes.
        # Closed-world continua de pe: quem responde tem que nomear alguem que o cadastro ja
        # conhece; um apelido novo explicado com outro apelido novo nao resolve nada.
        atribuicao = cadastro.atribuicao_em_texto(texto)
        if atribuicao.veredito != "resolvido" or atribuicao.modelo_id is None:
            return None
        aprendidos = await gravar_nomes_de_anuncio(
            conn, atribuicao.modelo_id, plano.nomes_desconhecidos
        )
        if not aprendidos:
            # O nome ja pertence a OUTRA mulher (UNIQUE global). Nao se muda o dono de um apelido
            # por uma frase no grupo — isso e cadastro, e cadastro se corrige no painel.
            #
            # O log e OBRIGATORIO aqui: o UNIQUE de `nome_normalizado` e global e vale tambem para
            # linha INATIVA, entao o apelido desativado no painel cai neste mesmo ramo. Visto do
            # grupo, o que acontece e mudo e inexplicavel — alguem responde "e a Duda", nada e
            # aprendido, a venda nunca nasce e o agente segue perguntando. Sem esta linha nao ha
            # em lugar nenhum o porque.
            _logger.warning(
                "grupo_financeiro_nome_de_anuncio_nao_aprendido modelo_id=%s nomes=%s "
                "mensagem_id=%s motivo=nome_ja_tem_dona_ou_apelido_inativo",
                atribuicao.modelo_id,
                list(plano.nomes_desconhecidos),
                base.mensagem_id,
            )
            return None
        _logger.info(
            "grupo_financeiro_nome_de_anuncio_aprendido modelo_id=%s nomes=%s mensagem_id=%s",
            atribuicao.modelo_id,
            list(aprendidos),
            base.mensagem_id,
        )
        cadastro = await carregar_cadastro_de_nomes(conn)

    plano = planejar(anuncio, cadastro=cadastro, dona_do_grupo=base.modelo_id)
    if plano.faltas or not plano.linhas:
        return None

    # O anuncio pode estar registrado PELA METADE (uma participante conhecida, a outra so agora).
    # Quem ja tem linha nao ganha outra: o dedup por conteudo pegaria a repeticao de qualquer
    # forma, mas ai o grupo levaria um aviso de duplicata que nao diz respeito a ele.
    ja_registradas = (
        {v.modelo_id for v in await vendas_da_mensagem(conn, anuncio_msg.id)}
        if anuncio_msg.tem_venda
        else set()
    )
    plano = replace(
        plano,
        linhas=tuple(linha for linha in plano.linhas if linha.modelo_id not in ja_registradas),
    )
    if not plano.linhas:
        return None

    return await _executar_plano(
        conn,
        base=base,
        plano=plano,
        anuncio=anuncio,
        data=anuncio_msg.dia(),
        mensagem_id=anuncio_msg.id,
        citar=anuncio_msg.evolution_message_id,
        contexto=contexto,
        enviar=enviar,
    )


# --- comum -------------------------------------------------------------------------------------


async def _executar_plano(
    conn: AsyncConnection[Any],
    *,
    base: ResultadoDaPorta,
    plano: PlanoDoAnuncio,
    anuncio: AnuncioDeVenda,
    data: date,
    mensagem_id: UUID,
    citar: str | None = None,
    contexto: Sequence[MensagemRegistrada],
    enviar: EnviarNoGrupo | None,
) -> ResultadoDaPorta:
    """Grava as Vendas registradas do plano, fala UMA vez no grupo e devolve as Pendencias.

    `mensagem_id` e a mensagem do ANUNCIO, mesmo quando quem destravou o registro foi uma
    resposta posterior: a origem auditavel da venda e onde o fato foi afirmado, e e essa
    mensagem que o ticket 05 usa como ancora de correcao e de anulacao por delecao.

    `citar` acompanha `mensagem_id` pelo mesmo motivo, do outro lado da fronteira: e o id do
    anuncio NA PLATAFORMA, e e ele que o recibo cita. Quando o registro foi destravado por uma
    resposta ("600"), citar a mensagem que entrou deixaria o recibo apontando para o "600" — e
    quem corrigisse respondendo esse recibo cairia num salto que nao chega em venda nenhuma
    (`vendas_da_mensagem_citada` anda recibo -> citada, e a citada precisa ser o anuncio). `None`
    = deixa o transporte citar a mensagem que entrou, que e o certo no caminho direto (anuncio
    completo), onde as duas coisas sao a mesma mensagem.

    Uma mensagem so, mesmo quando ha tres coisas a dizer (registrei / ja estava registrada /
    falta saber): o grupo e habitado por humanos que trabalham nele, e o agente que responde tres
    vezes ao mesmo anuncio vira ruido que ninguem le — inclusive a pergunta.
    """
    registradas: list[tuple[LinhaDoAnuncio, VendaRegistrada]] = []
    duplicadas: list[tuple[LinhaDoAnuncio, VendaRegistrada]] = []

    for linha in plano.linhas:
        chave = chave_de_conteudo(
            data=data, valor=linha.valor, modelo_id=linha.modelo_id, cliente=anuncio.cliente
        )
        venda = await registrar_venda(
            conn,
            modelo_id=linha.modelo_id,
            valor=linha.valor,
            data=data,
            mensagem_id=mensagem_id,
            chave_conteudo=chave,
            cliente_nome=anuncio.cliente,
            local_atendimento=anuncio.local,
            duracao_minutos=anuncio.duracao_minutos,
        )
        if venda is not None:
            registradas.append((linha, venda))
            continue
        ja_existente = await venda_por_chave_de_conteudo(conn, chave)
        if ja_existente is not None:
            duplicadas.append((linha, ja_existente))

    falas: list[str] = []
    if registradas:
        falas.append(
            montar_recibo(
                linhas=[(linha.nome, venda.valor) for linha, venda in registradas],
                data=data,
                cliente=anuncio.cliente,
                duracao_minutos=anuncio.duracao_minutos,
                local=anuncio.local,
            )
        )
    if duplicadas:
        falas.append(
            montar_aviso_de_duplicata(
                linhas=[(linha.nome, venda.valor) for linha, venda in duplicadas],
                data=data,
                cliente=anuncio.cliente,
            )
        )
    pergunta = _pergunta_do_plano(plano, cliente=anuncio.cliente, contexto=contexto)
    if pergunta is not None:
        falas.append(pergunta)

    resposta = "\n".join(falas) if falas else None
    if resposta is not None:
        await _postar(enviar, resposta, citar=citar)

    motivo = _motivo_do_plano(plano, duplicadas=bool(duplicadas))
    for linha, venda in registradas:
        GRUPO_FINANCEIRO_ANUNCIOS.labels("venda_registrada").inc()
        _logger.info(
            "grupo_financeiro_venda_registrada venda_id=%s modelo_id=%s valor=%s data=%s",
            venda.id,
            linha.modelo_id,
            venda.valor,
            venda.data,
        )
    for linha, venda in duplicadas:
        GRUPO_FINANCEIRO_ANUNCIOS.labels("venda_duplicada").inc()
        _logger.info(
            "grupo_financeiro_venda_duplicada venda_id=%s modelo_id=%s mensagem_id=%s",
            venda.id,
            linha.modelo_id,
            base.mensagem_id,
        )
    if motivo is not None and motivo != "venda_duplicada":
        GRUPO_FINANCEIRO_ANUNCIOS.labels(motivo).inc()
        _logger.info(
            "grupo_financeiro_anuncio_sem_venda motivo=%s grupo_id=%s mensagem_id=%s nomes=%s",
            motivo,
            base.grupo_id,
            base.mensagem_id,
            list(plano.nomes_desconhecidos),
        )

    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        # Uma linha so: a modelo dela. Duas: nao ha "a modelo desta mensagem" — a dona do grupo
        # e a resposta honesta, e quem quer as duas le `vendas`.
        modelo_id=registradas[0][1].modelo_id if len(registradas) == 1 else base.modelo_id,
        mensagem_id=base.mensagem_id,
        vendas=tuple(venda.id for _, venda in registradas),
        pendencias=tuple(p for _, venda in registradas for p in pendencias_da_venda(venda)),
        resposta=resposta,
        motivo=motivo,
    )


def _motivo_do_plano(plano: PlanoDoAnuncio, *, duplicadas: bool) -> MotivoSemVenda | None:
    """O que ficou por fazer com este anuncio. `None` = fez tudo.

    Precedencia deliberada: o que FALTA vence o que duplicou, porque e a falta que ainda espera
    alguem. `motivo` conviver com `vendas` nao vazio e normal desde o anuncio de duas modelos —
    uma participante registrada e a outra ainda por identificar e o caso comum de 10/08.
    """
    if plano.faltas:
        return "sem_valor" if "valor" in plano.faltas else "nome_desconhecido"
    if duplicadas:
        return "venda_duplicada"
    if plano.ambiguo:
        return "nome_ambiguo"
    return None


def _pergunta_do_plano(
    plano: PlanoDoAnuncio, *, cliente: str | None, contexto: Sequence[MensagemRegistrada]
) -> str | None:
    """A pergunta minima deste anuncio — ou `None` quando perguntar seria repetir.

    Perguntar em vez de registrar pela metade e a escolha certa aqui porque venda sem valor (ou
    de modelo desconhecida) nao e uma venda incompleta: e uma linha que entraria errada no
    extrato de alguem e nunca mais seria olhada.

    O que NAO se repete e a pergunta por um nome: se o agente ja perguntou por "fran loira" no
    grupo e ninguem respondeu ainda, perguntar de novo a cada anuncio dela e a metralhadora que
    o dominio proibe. Falta de VALOR nao entra nessa regra — cada anuncio tem o valor dele.
    """
    if not plano.faltas:
        return None
    if plano.faltas == ("modelo",) and _ja_perguntou_pelos_nomes(
        contexto, plano.nomes_desconhecidos
    ):
        return None
    return montar_pergunta_minima(
        faltas=plano.faltas,
        cliente=cliente,
        nomes_desconhecidos=plano.nomes_desconhecidos,
        por_modelo=plano.por_modelo,
    )


def _ja_perguntou_de_qual_venda(contexto: Sequence[MensagemRegistrada]) -> bool:
    """O agente ja pediu para desempatar a forma no que se ve do grupo?

    Mesma tranca do `_ja_perguntou_pelos_nomes`, e pelo mesmo motivo: quem responde "pix" sem
    nomear tende a repetir "pix" sem nomear, e uma pergunta por repeticao vira a metralhadora
    que o dominio proibe. Uma pergunta por janela de contexto e o teto; passada ela, perguntar de
    novo e legitimo porque a primeira se perdeu na conversa.

    Nao repara em QUAL forma foi perguntada: o que a pergunta pede e o nome do cliente, e esse
    pedido e o mesmo tenha ela dito pix ou dinheiro.
    """
    return any(m.de_mim and m.texto.startswith(PREFIXO_DO_DESEMPATE) for m in contexto)


def _ja_perguntou_pelos_nomes(
    contexto: Sequence[MensagemRegistrada], nomes: tuple[str, ...]
) -> bool:
    """O agente ja perguntou por estes nomes no que se ve do grupo?

    Derivado do log de origem, como todo estado deste modulo — a pergunta do agente volta pelo
    webhook como mensagem `de_mim` e fica gravada. O alcance e o da janela de contexto: passados
    dois dias sem ninguem responder, perguntar de novo e legitimo (a primeira se perdeu na
    conversa), e e por isso que isto le o contexto em vez de um "ja perguntei" eterno.
    """
    if not nomes:
        return False
    alvos = [normalizar(nome) for nome in nomes]
    return any(
        m.de_mim
        and PREFIXO_DA_PERGUNTA in m.texto
        and all(alvo in normalizar(m.texto) for alvo in alvos)
        for m in contexto
    )


def _parece_resposta_curta(texto: str) -> bool:
    """Vale a pena relê o grupo por causa desta mensagem?

    Resposta de pergunta minima e telegrafica ("600", "é a Duda", "600 1h"). Paragrafo nao e
    resposta — e conversa, e conversa sai da porta sem custar consulta nenhuma.
    """
    palavras = _PALAVRA.findall(texto)
    return 0 < len(palavras) <= MAX_PALAVRAS_DA_RESPOSTA


MAX_PALAVRAS_PARA_A_LLM = 25
"""Teto de custo do leitor de texto — mais largo que o da allowlist, e de proposito.

O teto apertado existia porque a allowlist so acertava frase telegrafica; com a LLM lendo, o que
sobra fora dele e a frase que ela leria BEM ("foi tudo no pix, menos o do Igor que pagou em
dinheiro" tem 13 palavras e nao passaria por 6). Continua sendo teto e nao ausencia de teto:
paragrafo do grupo e conversa, e conversa nao vale uma ida ao provider a cada mensagem.
"""


def _vale_ler(texto: str, *, com_llm: bool) -> bool:
    """A mensagem merece que a porta gaste alguma coisa com ela?

    Dois tetos porque sao dois leitores com alcances diferentes — usar o teto da allowlist com a
    LLM plugada seria pagar pelo provider e continuar surdo justamente na frase comprida, que e a
    que a allowlist nunca pegou.
    """
    palavras = _PALAVRA.findall(texto)
    teto = MAX_PALAVRAS_PARA_A_LLM if com_llm else MAX_PALAVRAS_DA_RESPOSTA
    return 0 < len(palavras) <= teto


def _sem_venda(
    base: ResultadoDaPorta,
    motivo: MotivoSemVenda,
    *,
    nomes: tuple[str, ...] = (),
    resposta: str | None = None,
) -> ResultadoDaPorta:
    """A mensagem nao virou venda — com ou sem o agente ter falado algo a respeito."""
    GRUPO_FINANCEIRO_ANUNCIOS.labels(motivo).inc()
    if motivo not in ("nao_e_anuncio", "eco_do_agente", "pergunta_de_pagamento"):
        _logger.info(
            "grupo_financeiro_anuncio_sem_venda motivo=%s grupo_id=%s mensagem_id=%s nomes=%s",
            motivo,
            base.grupo_id,
            base.mensagem_id,
            list(nomes),
        )
    return ResultadoDaPorta(
        status=base.status,
        grupo_id=base.grupo_id,
        modelo_id=base.modelo_id,
        mensagem_id=base.mensagem_id,
        resposta=resposta,
        motivo=motivo,
    )


def _exigir_mensagem(base: ResultadoDaPorta) -> UUID:
    if base.mensagem_id is None:  # pragma: no cover - so se chega aqui apos registrar a mensagem
        raise RuntimeError("venda sem mensagem-fonte")
    return base.mensagem_id


async def _registrar_a_propria_fala(
    conn: AsyncConnection[Any],
    resultado: ResultadoDaPorta,
    *,
    msg: MensagemDoGrupo,
    enviar: EnviarNoGrupo | None,
) -> None:
    """Poe a fala que o agente acabou de dar no log de origem, na hora — sem esperar o eco.

    Todo "ja falei disto?" deste modulo (`_ja_perguntou_de_qual_venda`,
    `_ja_perguntou_pelos_nomes`, as trancas da divergencia e do comunicado) e estado DERIVADO do
    log: a pergunta do agente aparece la como mensagem `de_mim` e por isso a segunda passada fica
    calada. Ate aqui quem punha essa linha era o **eco** — a propria fala voltando pela Evolution
    como `fromMe` alguns instantes depois.

    O eco chega tarde demais para a duplicata. A mesma fala reentregue com outro `message_id` (o
    router duplicando fora da janela de dedup, o retry da Evolution) passa pela porta ANTES de o
    eco da primeira ter voltado: as duas passadas leem um log sem pergunta nenhuma e as duas
    perguntam. E a metralhadora que o dominio proibe, e ela nao aparece em teste que simula o eco
    a mao — so em producao, no dia em que o router duplicar.

    Escrever a linha aqui e a mesma coisa que a rotina da manha ja faz com a fala dela
    (`reservar_fala_da_rotina`): o agente registra o que disse, ponto. Quando o eco voltar ele
    tera outra `chave_dedup` (`evo:<id>` contra a de conteudo) e entrara como segunda linha
    identica — barulho no log, e o preco certo a pagar para nao perguntar duas vezes sobre
    dinheiro.

    Sem BOCA nao se registra nada, e essa condicao e a definicao do que esta linha significa: o
    log de origem e o que foi DITO no grupo. Com `enviar=None` (replay do export, backfill, teste
    que so quer a decisao) a porta decide a fala e nao a diz — grava-la ali inventaria no
    historico uma mensagem que ninguem leu, e a proxima passada ficaria calada por causa dela.

    Best-effort no mesmo sentido do `_postar`: sem `grupo_id` (grupo nao cadastrado) ou sem fala
    nao ha o que registrar.
    """
    if enviar is None or resultado.resposta is None or resultado.grupo_id is None:
        return
    await registrar_mensagem(
        conn,
        resultado.grupo_id,
        MensagemDoGrupo(
            grupo_jid=msg.grupo_jid,
            texto=resultado.resposta,
            de_mim=True,
            recebida_em=msg.recebida_em,
        ),
    )


async def _postar(enviar: EnviarNoGrupo | None, texto: str, *, citar: str | None = None) -> None:
    """Entrega best-effort: falhar ao FALAR nunca desfaz o que ja foi REGISTRADO.

    A venda ja esta no banco quando chegamos aqui. Levantar agora abortaria a transacao do
    webhook e a mensagem voltaria pelo retry da Evolution, refazendo tudo por causa de um timeout
    de rede — o recibo perdido e o mal menor (e o painel mostra a venda de qualquer jeito).

    O recibo sai DENTRO da transacao de quem chamou (o commit e do webhook, no fim do `with`).
    Assumido: um rollback depois daqui deixaria um recibo sem venda — falha rara e visivel (a
    gestora corrige por quote, ticket 05) contra o custo de uma segunda rodada de entrega so
    para adiar a fala.
    """
    if enviar is None:
        return
    try:
        await enviar(texto, citar=citar)
    except Exception:
        _logger.warning("grupo_financeiro_recibo_nao_enviado", exc_info=True)


def de_evolution(
    msg: MensagemEvolution,
    *,
    recebida_em: datetime | None = None,
    midia: tuple[bytes, str] | None = None,
) -> MensagemDoGrupo:
    """Adaptador envelope-da-Evolution -> entrada da porta.

    Fica DESTE lado (e nao no `routes.py`) para o teste da porta exercitar a mesma traducao que a
    producao faz: e aqui que se decide o que conta como autor e o que conta como texto. O
    `sender_jid` (participant) e o autor real no grupo — `remote_jid` e o grupo, nunca a pessoa.

    `midia` e o par `(bytes, content_type)` que o webhook ja tem em maos quando o evento traz
    audio ou imagem (base64 inline, download host-locked ou bucket da EvoGo — tres caminhos que so
    o webhook conhece). Ela vira `AudioDoGrupo` ou `ImagemDoGrupo` conforme o tipo, e nada quando
    o tipo e outro: carregar bytes que ninguem vai ler seria so peso.
    """
    audio = (
        AudioDoGrupo(conteudo=midia[0], mimetype=midia[1] or msg.media_mimetype)
        if midia is not None and msg.tipo == "audio"
        else None
    )
    imagem = (
        ImagemDoGrupo(conteudo=midia[0], mimetype=midia[1] or msg.media_mimetype)
        if midia is not None and msg.tipo == "imagem"
        else None
    )
    return MensagemDoGrupo(
        grupo_jid=msg.remote_jid,
        texto=msg.texto,
        tipo=msg.tipo,
        audio=audio,
        imagem=imagem,
        evolution_message_id=msg.evolution_message_id or None,
        autor_jid=msg.sender_jid,
        autor_nome=msg.push_name,
        de_mim=msg.from_me,
        caption=msg.caption,
        media_url=msg.media_url,
        quoted_message_id=msg.quoted_message_id,
        recebida_em=recebida_em or datetime.now(UTC),
    )


def delecao_de_evolution(
    evento: DelecaoEvolution, *, ocorrida_em: datetime | None = None
) -> DelecaoNoGrupo:
    """Adaptador envelope-da-Evolution -> entrada da porta, para o evento de delecao.

    Fica do mesmo lado e pelo mesmo motivo que `de_evolution`: o teste da porta tem que exercitar
    a traducao que a producao faz. O `participant` e quem apagou — guardado como autor por
    simetria com a mensagem, mesmo que hoje so o carimbo importe.
    """
    return DelecaoNoGrupo(
        grupo_jid=evento.remote_jid,
        evolution_message_id=evento.evolution_message_id,
        autor_jid=evento.participant,
        ocorrida_em=ocorrida_em or datetime.now(UTC),
    )
