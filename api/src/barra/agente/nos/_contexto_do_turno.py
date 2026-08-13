"""`ContextoDoTurno`: o dicionário de propósito do turno, declarado uma vez e tipado.

É o contrato da cauda volátil — o MESMO conjunto de campos alimenta os dois blocos que saem dele:
`contexto_dinamico.md.j2` (o que a IA lê) e `ja_registrado.md.j2` (o que o EXTRATOR lê, via
`PecasDoTurno` no State). Era um `dict[str, Any]` montado num `return` de 70 linhas: um rename de
chave não quebrava nada — o Jinja renderiza variável desconhecida como VAZIA, então o bloco sumia
do prompt em silêncio e a IA perdia a instrução em produção.

Aqui o rename vira erro de mypy no ponto de construção, e o que amarra a outra ponta (as
variáveis que os templates de fato leem, mais o espelho da bancada offline) é
`tests/unit/test_contrato_variaveis_contexto.py`.

`frozen=True` de propósito: as duas correções que rodam DEPOIS de resolver o contexto (o A2 do dia
e o OR da sondagem, em `_anexar_contexto_dinamico`) passam a ser `replace(...)` explícito, com o
campo nomeado no diff, em vez de mutação in-place de um dicionário anônimo — a ordem entre elas e
o render do bloco de estado é semântica (ver `_anexar_contexto_dinamico`).
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any


@dataclass(frozen=True)
class ContextoDoTurno:
    """Variáveis do turno resolvidas por `_resolver_variaveis` (02 §5). Ver o módulo."""

    # Âncora de tempo. `agora` é a âncora CRUA (BRT naive) — os templates não a leem, ela viaja
    # para a janela dedicada da extração (`PecasDoTurno`); `data_atual`/`hora_atual` são as
    # DERIVADAS que a IA lê no `<agenda>`. Sair da mesma fonte é o que impede divergência.
    agora: datetime | None
    data_atual: date | None
    hora_atual: str | None

    # Atendimento e belief-state (derivado da MESMA FSM da extração).
    numero_curto: int | None
    estado: str | None
    # Só EXIBIÇÃO (contrato F32): o enum humanizado que os templates imprimem. A LÓGICA continua
    # lendo o campo cru (`estado`/`tipo_atendimento`), nunca estes. `tipo_humano` é None quando o
    # tipo ainda não foi escolhido — o template aplica o `or 'ainda não definido'`.
    estado_humano: str | None
    tipo_humano: str | None
    slots_faltantes: list[str]
    proximo_passo: str
    # A `proxima_acao_esperada` que a EXTRAÇÃO do turno anterior gravou (obrigatória todo turno,
    # ja_registrado.md.j2) — renderizada de volta como <acao_pendente>: é a leitura mais fresca do
    # que a conversa pede, enquanto o <proximo_passo> deriva do estado (um turno atrás). Diagnóstico
    # 11/08: ela acertava o alvo ("enviar o endereço") e nunca chegava ao chat.
    acao_pendente: str | None
    # A `intencao` crua não é renderizada no contexto dinâmico (vira <ainda_falta>/<proximo_passo>);
    # está aqui porque o <ja_registrado> precisa dela p/ o extrator saber que já está registrada.
    intencao: str | None
    tipo_atendimento: str | None
    urgencia: str | None
    pix_status: str
    data_desejada: date | None
    horario_desejado: time | None
    horario_ja_combinado: bool
    horario_evidenciado: bool
    endereco: str | None
    bairro: str | None
    valor_fechado: str | None
    valor_aceito: bool
    duracao_fechada: str | None

    # Flags de disciplina materializadas no write-time (padrão A2 — agente/CLAUDE.md).
    # `dia_ja_sondado_hist` é a coluna crua; quem os templates leem é `dia_ja_sondado`, o OR dela
    # com o window-scan do turno (aplicado em `_anexar_contexto_dinamico`).
    n_contrapropostas: int
    # Em que ponto a escada de desconto está NESTE encontro (`estado_da_escada`, atendimentos/
    # service): "sem_dia" (o dia não está na mesa — não se desconta, sonda-se o dia), "aberta"
    # (ainda há mais de uma contraproposta), "ultima" (a disponível é a final) ou "esgotada".
    # O contador sozinho deixou de bastar quando a escada passou a depender do dia: com encontro
    # HOJE existe UMA contraproposta (o piso direto), com outro dia existem duas.
    escada_estado: str
    # Pendurado no estado acima, não é flag nova: o VALOR da próxima contraproposta, já calculado,
    # para a IA parar de multiplicar o percentual de cabeça em cima da tabela. Sai da mesma
    # família de função que JULGA a oferta (`contraproposta_da_escada`, atendimentos/service);
    # None (sem cotação em aberto, escada fechada ou tabela ambígua) = a cauda não injeta número
    # e vale a prosa do <desconto> do BP_GERAL.
    contraproposta_disponivel: str | None
    # O valor que o CLIENTE nomeou NESTE burst quando ele serve (ADR-0040): `[piso, mesa)`, com a
    # duração resolvida e a escada não esgotada. É o número que fecha a venda — dela sai só o sim.
    # Excludente com `contraproposta_disponivel` na origem (com aceite a escada nem é consultada) e
    # de novo no template, que os põe na MESMA cadeia `{% if %}/{% elif %}`: dois números na mesma
    # mensagem seriam duas ofertas. None = ele não nomeou valor, nomeou mais de um, pediu abaixo do
    # piso, pediu acima da mesa, o pacote está ambíguo ou a escada acabou — tudo cai na escada dela.
    aceite_do_valor_dele: str | None
    # O dia do encontro como a escada o enxerga ("hoje" | "outro_dia" | "dia_desconhecido").
    # Dado do turno, não instrução: é o que faz o bloco falar de "vir hoje" ou de descobrir o dia.
    encontro_do_dia: str
    # O patamar em que o valor da MESA já está ("cheio" | "degrau" | "piso"), derivado do encontro
    # + do contador. O extra de fetiche desce por ele (ADR-0038): é o que permite pré-computar o
    # total "pacote + extra" no mesmo patamar em vez de mandar a IA somar.
    patamar_da_mesa: str
    # Há preço cotado ainda não aceito (`cotacao_enviada_em` ou `valor_acordado`, sem
    # `aceita_valor`) — a janela em que uma objeção de preço pode chegar. Gate dos dois blocos da
    # rodada n=0: o que injeta o número da contraproposta e o que explica que sem o dia não há
    # número. Sem preço na mesa não há desconto a falar, e o número solto convidaria a ofertar
    # antes de ele pedir.
    preco_na_mesa: bool
    n_perguntas_de_horario: int
    dia_ja_sondado_hist: bool
    book_ja_enviado: bool
    endereco_ja_enviado: bool
    amiga_ja_ofertada: bool
    foto_portaria_ja_pedida: bool
    motivo_resgate_ja_perguntado: bool

    # Ponto de encontro, já gated por estado/tipo (`_libera_local_de_encontro`). `local_endereco`
    # chega no degrau do estado — SEM o número da rua antes de o encontro estar de pé.
    local_endereco: str | None
    local_nome: str | None
    # Degrau do número, por ESTADO só (`_libera_numero_do_endereco`) — vale mesmo onde não há local
    # (externo/remoto); os templates só o leem dentro do `{% if local_endereco %}`. É o que faz a
    # instrução do bloco acompanhar o degrau em vez de mandar esconder um dado que ela tem.
    numero_liberado: bool

    # Cardápio e cliente.
    tabela_max_horas: float
    sem_periodo_longo: bool
    # Gate do cardápio de ATOS, da mesma leitura de fetiches do BP_MODELO: sem nenhum vínculo em
    # `modelo_fetiches` o <fetiches> dela sai "(sem fetiches cadastrados)" — não há extra a cotar
    # nem linha "Inclusos", e a cauda injeta o <sem_fetiches>. Mesma família derivada do cardápio.
    sem_fetiches: bool
    # Gate do <composicoes>, derivado do cardápio dela (mesma leitura de fetiches do BP_MODELO): sem a
    # seção "Por pessoa" no <fetiches>, menage/casal não existe pra ela e a cauda injeta o
    # <sem_menage>. É o padrão do `sem_periodo_longo` — a condição vira dado, não prosa.
    sem_menage: bool
    # Mesmo trilho para a vídeo chamada (ADR-0021/0029): sem o programa na tabela dela (as mesmas
    # linhas de `modelo_programas` que o <programas> do BP_MODELO renderiza), a chamada não é dela
    # e a cauda injeta o <sem_video_chamada> — a prosa que negava isso em quatro sites do BP_GERAL
    # sai. Default conservador `False` (não injeta) igual aos dois acima.
    sem_video_chamada: bool
    # Mesmo trilho para o formato externo (F16): sem "externo" nos tipos aceitos dela, o
    # deslocamento/uber não existe no cardápio e o bloco_da_modelo injeta o <sem_externo>. Derivado
    # do cadastro (`tipo_atendimento_aceito`), como os `sem_*` acima; default conservador `False`.
    sem_externo: bool
    recorrente: bool
    observacoes_internas: str | None
    ultimo_motivo_perda: str | None
    cliente_nome: str | None
    historico_anteriores: str | None

    # Agenda das próximas 48h, com a aritmética já feita em Python (a IA só verbaliza).
    bloqueios: list[dict[str, Any]]
    disponibilidade: list[dict[str, Any]]
    horario_minimo: datetime | None
    proximo_horario: datetime | None
    janelas_livres: list[tuple[datetime, datetime]]

    # Percepção de tempo na cauda (emenda ADR 0025).
    min_desde_ultima_msg_cliente: int | None
    combinado_hora: str | None
    min_para_combinado: int | None

    # Resolvidos depois das queries, sobre a janela do turno — default para a construção não
    # precisar antecipá-los (ver `_anexar_contexto_dinamico`).
    dia_ja_sondado: bool = False
    # O rótulo do dia do encontro ("hoje" | "ainda hoje (madrugada)" | "amanhã" | "em N dias" |
    # "já passou"), resolvido em Python DEPOIS do A2 do dia (`_quando_do_encontro`). Vem daqui e
    # não de uma conta no template porque `(data_desejada - data_atual).days` mente na virada da
    # madrugada: encontro 00:30 marcado 23:39 vira "amanhã" e a IA manda "confirma amanhã de manhã"
    # para daqui a 51 minutos. É rótulo de EXIBIÇÃO — a escada de desconto segue lendo o
    # `encontro_do_dia`, que é por calendário. None = sem dia gravado (o template omite o atributo).
    quando_encontro: str | None = None
    # O NÚMERO da cotação vigente quando o belief não tem nenhum — a fala DELA na janela é a fonte
    # (`_preco_cotado_na_janela`). Existe porque `preco_na_mesa` liga por `cotacao_enviada_em` e
    # `valor_acordado` só é gravado no ACEITE: sem isto a tag <valor_cotado> abria e renderizava
    # VAZIA no turno da objeção. Só é resolvido no cruzamento estreito (preço na mesa, sem
    # `valor_fechado` e sem `pacote_em_pauta`); None = sem número seguro, e o template OMITE a tag.
    preco_cotado_valor: str | None = None
    # Ela já falou nesta parte da conversa? Gate do "não recumprimente" do `<antes_de_perguntar>`:
    # sem ele a cauda proibia, no ponto de recency máxima, a abertura que a `<abertura>` prescreve.
    conversa_em_andamento: bool = False

    # <foco_do_turno> (re-ancoragem por turno, rodada 3): o que o burst ATUAL do cliente pede,
    # detectado deterministicamente sobre a janela limpa (`nos/_foco_do_turno.py`) e aplicado por
    # `replace()` em `_anexar_contexto_dinamico`, como os outros campos resolvidos pós-query.
    # Defaults conservadores: sem detecção, o bloco não renderiza e nada muda no prompt.
    perguntas_do_turno: tuple[str, ...] = ()
    pediu_endereco_no_turno: bool = False
    pediu_preco_no_turno: bool = False
    # A linha da tabela para a duração em discussão ({"horas": "1", "preco": "R$ 500"}) — SÓ
    # quando a duração está em pauta SEM valor cotado e ela tem UM preço na tabela (o mesmo
    # fail-closed da escada de desconto: com dois preços o pacote é ambíguo e o número
    # errado seria pior que nenhum). Com valor já cotado quem ancora é o <valor_cotado>.
    pacote_em_pauta: dict[str, str] | None = None
    # A saudação de período do burst atual ("bom dia"/"boa tarde"/"boa noite") — rodada 4:
    # espelhamento determinístico; o foco a injeta como dado ("espelhe a dele") e o gatilho
    # `saudacao` do guard pega o período conflitante. None = ele não saudou = nada renderiza.
    saudacao_dele: str | None = None
    # Rodada 6 — o avanço com NÚMERO: a disponibilidade concreta já computada pela aritmética da
    # agenda ("livre hoje a partir de 22:00"), para o avanço do foco sair com hora em vez de
    # "seria hoje?" vago (derrota medida: preço nu / confirmação decorativa, fechamento 77%).
    # None = agenda sem âncora = os blocos degradam para o avanço sem número (fail-closed).
    livre_agora: str | None = None
    # Rodada 6 — burst atual é SÓ aceite curto ("Perfeito"/"Certo"): o turno é de avançar, não de
    # repetir preço/pitch já dados (derrota medida: re-cotação pós-aceite). Vocabulário fechado
    # de `_e_afirmacao_curta`; False = nada muda no prompt.
    aceitou_no_burst: bool = False
    # Rodada 6b — closed-world do cardápio como DADO do turno (recusa_limite 71%): as famílias de
    # fetiche/serviço que o burst menciona, JÁ resolvidas contra o cadastro dela
    # (`_resolver_fetiches_em_pauta`): {"nome": rótulo, "status": incluso|extra|por_pessoa|
    # no_completo|fora}. Vazio = nada renderiza (fail-closed: sem cadastro carregado, sem bloco).
    fetiches_em_pauta: tuple[dict[str, str], ...] = ()
    # Os NOMES do cardápio de fetiches dela, como estão cadastrados. Só o bloco do EXTRATOR
    # (`ja_registrado.md.j2`) os lê: com `extracao_no_modelo_barato` a janela dedicada troca o
    # BP_GERAL por um system mínimo, então a tabela `<fetiches>` NÃO viaja até lá e o extrator não
    # tinha como traduzir a palavra do cliente ("pegging") para o nome canônico ("Inversão") que
    # `registrar_fetiches_do_fechamento` casa por nome exato (o resto ele descarta em silêncio).
    # Vazio = a tag não renderiza (fail-closed, igual ao `fetiches_em_pauta`).
    fetiches_do_cadastro: tuple[str, ...] = ()
    # Ele perguntou limites/restrições no burst — o foco injeta a resposta-cardápio (os Inclusos
    # nominais abaixo), nunca "nenhuma restrição".
    pediu_restricoes: bool = False
    inclusos_nomes: tuple[str, ...] = ()
    # Primeira cotação da conversa com tabela de DUAS portas (entrada + Completo): o menu pronto
    # ("400 na 1 hora; Completo 800 na 1 hora") — as duas saem juntas (emenda da <cotacao>,
    # rodada 6b). None = sem menu (já cotou, tabela não é de duas portas, ou sem dado).
    menu_primeira_cotacao: str | None = None
    # Casal/menage em pauta na JANELA (não só no burst) e a modelo tem a seção "Por pessoa": nota
    # condicional de que a cotação para 2 sai da seção "Por pessoa" (derrota medida: cotava
    # individual p/ casal). Desde o ADR-0039 o número dessa seção não é mais o pacote dobrado.
    composicao_em_pauta: bool = False
    # O TOTAL das duas pessoas no patamar já negociado (pacote + o extra da 2ª pessoa no MESMO
    # patamar, ADR-0039: soma UM extra, o pacote NÃO dobra), pré-computado quando a `composicao_em_pauta`
    # vale E a negociação já saiu do cheio. É o que deixa o bloco COTAR em vez de cair no "não cota →
    # escala": sem ele, a tabela cheia do <fetiches> não vale sobre pacote descontado e não havia
    # número. None = patamar cheio (a tabela "Por pessoa" estática já é o número) ou sem total pronto
    # (sem item por-pessoa/sem linha de 1h) — e aí o fallback conservador do bloco vale.
    composicao_total: str | None = None
    # --- Oferta condicionada ao dia (ADR-0041) ---------------------------------------------------
    # O PAR já calculado da linha em pauta: `oferta_se_hoje` = o piso, `oferta_se_outro_dia` = o
    # degrau (`oferta_condicionada_ao_dia`, atendimentos/service). Só existem no cruzamento estreito
    # em que a conduta vale: dia ainda desconhecido, escada intacta, preço na mesa e o valor cotado
    # sendo um SALTO sobre o que já estava na mesa (composição, fetiche pago, pacote maior). Os DOIS
    # vêm juntos ou nenhum vem — dizer o número de hoje sem ter o do outro dia é o que faz a resposta
    # dele ("então outro dia") parecer aumento de preço.
    oferta_se_hoje: str | None = None
    oferta_se_outro_dia: str | None = None
    # --- Subir o tempo antes de descer o preço ---------------------------------------------------
    # O pacote MAIOR que existe na tabela dela acima da duração em pauta ({"horas": "2",
    # "preco": "800"}), com o mesmo fail-closed de sempre (só a duração com UM preço presencial).
    # É dado, não instrução: é o prompt que diz que subir o tempo vem antes de descer o preço, e a
    # fala é dela. None = não há pacote maior (ou a tabela é ambígua) e o bloco não renderiza.
    pacote_maior: dict[str, str] | None = None
    # Ele nunca nomeou uma duração na janela — a duração em pauta é a que ELA cotou. É o que separa
    # a sondagem de DURAÇÃO (vender 2h) da sondagem de DIA: são coisas diferentes e não podem se
    # confundir. Com a duração dita por ele, o bloco não pergunta o tempo; só oferece o pacote maior.
    tempo_dele_desconhecido: bool = False

    # --- Parceira (ADR-0042) ---------------------------------------------------------------------
    # Os dois fluxos que partem da MESMA pessoa e divergem em tudo. `parceira_fluxo` é a saída do
    # discriminante determinístico (`agente/_parceria.py:fluxo_da_parceira`) — "encaminhamento",
    # "dupla" ou None — e é ele que escolhe qual tag renderiza. Nunca as duas: o discriminante
    # devolve UM valor, e o template lê UM campo.
    #
    # `parceira_nome` é o único dado dela que chega ao prompt. O TELEFONE nunca entra aqui (nem em
    # campo nenhum do contexto): ele é lido fresh pelo coordenador, depois do turno, e sai como
    # bolha determinística — o trilho da chave Pix.
    parceira_nome: str | None = None
    parceira_fluxo: str | None = None
    # O rótulo humano do ato que armou o encaminhamento ("anal") — só no fluxo A, para a fala dela
    # nomear o que ela não faz sem consultar o cardápio de novo.
    parceira_ato: str | None = None
    # Carimbos duráveis do atendimento: a trava "uma vez por atendimento" do encaminhamento e o
    # "esta venda já é das duas" da dupla. Ambos sobrevivem à janela (_JANELA_MENSAGENS), como as outras
    # flags A2 — e ambos são também travas de write-time na tool (`envolver_parceira`).
    parceira_ja_encaminhada: bool = False
    parceira_dupla_assumida: bool = False
    # So o <ja_registrado> (janela da extracao) le: o extrator precisa saber que a forma de
    # pagamento JA esta gravada — ela foi inventada e nunca revertida em prod (2x no diag 11/08),
    # e campo invisivel no bloco de estado e campo que ninguem corrige.
    forma_pagamento: str | None = None

    def como_variaveis(self) -> dict[str, Any]:
        """Dicionário para o `render(**variaveis)` dos templates. Raso de propósito: os valores
        (datetimes, listas de bloqueio) vão por referência, como iam quando isto era um dict."""
        return dict(vars(self))
