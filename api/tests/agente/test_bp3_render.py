"""Aceite M2-T1 — BP3 por-modelo (identidade + programas) renderizado e cacheado.

DB-free e key-free: monta `IdentidadeModelo` à mão + programas mock e exercita
`render_identidade`/`render_programas`/`render_bp3`/`build_system_messages`. O carregamento
das queries do `prepare_context` é coberto em `test_contexto_dinamico.py` (needs_db).

Guard-rail #1 (agente/CLAUDE.md): BP_GERAL sai byte-idêntico entre 2 modelos distintas; só o
BP_MODELO difere. Vazar dado por-modelo no BP_GERAL derruba o cache de TODAS.
"""

from typing import Any

from barra.agente.llm import build_system_messages
from barra.agente.persona import (
    IdentidadeModelo,
    render_bp3,
    render_fetiches,
    render_identidade,
    render_programas,
)

GERAL = "<persona>voz geral</persona>"

CARIOCA = IdentidadeModelo(
    nome="Bia",
    idade=26,
    idiomas=["pt-BR"],
    localizacao_operacional="Barra da Tijuca",
    tipos_aceitos=["interno", "externo"],
)

ESTRANGEIRA = IdentidadeModelo(
    nome="Ivanka",
    idade=29,
    idiomas=["pt-BR", "en-US"],
    localizacao_operacional=None,
    tipos_aceitos=["externo"],
)

PROGRAMAS: list[dict[str, Any]] = [
    {"nome": "Massagem Relaxante", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 800},
    {"nome": "Massagem Relaxante", "duracao_nome": "2 horas", "duracao_horas": 2, "preco": 1500},
    # Programa SEM linha de 1h: sob o ADR-0038 não há extra derivado pra ele (o extra É a 1h),
    # então ele não vira linha na tabela de atos — nem na seção "Por pessoa", desde o ADR-0039
    # (o regime velho dela dobrava o pacote e dispensava a 1h; o novo é o mesmo dos atos).
    {"nome": "Programa Completo", "duracao_nome": "2 horas", "duracao_horas": 2, "preco": 2500},
]

# Tabela canônica da decisão de 11/08/2026 (Catarina, programa Normal): 30min sem extra, e o
# extra de +R$400 (a 1h dela) somando igual em 1h, 2h, 3h e pernoite.
PROGRAMAS_CATARINA: list[dict[str, Any]] = [
    {"nome": "Normal", "duracao_nome": "30 minutos", "duracao_horas": 0.5, "preco": 250},
    {"nome": "Normal", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 400},
    {"nome": "Normal", "duracao_nome": "2 horas", "duracao_horas": 2, "preco": 800},
    {"nome": "Normal", "duracao_nome": "3 horas", "duracao_horas": 3, "preco": 1000},
    {"nome": "Normal", "duracao_nome": "Pernoite", "duracao_horas": 12, "preco": 2000},
]

FETICHES_CATARINA: list[dict[str, Any]] = [
    {"nome": "Beijo na boca", "preco": None, "cobra_por_pessoa": False},
    {"nome": "Inversão", "preco": 1, "cobra_por_pessoa": False},
]

# Vídeo chamada na tabela (Catarina, 11/08/2026): R$10/min, e a linha de 60min tem `horas = 1` —
# passa no filtro de duração e viraria "Vídeo chamada (1h) | R$1.000" se a exclusão fosse só por
# duração. Fetiche pago é de programa PRESENCIAL (ADR-0021: a chamada é o único serviço remoto).
PROGRAMAS_COM_VIDEO: list[dict[str, Any]] = [
    {"nome": "Normal", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 400},
    {"nome": "Vídeo chamada", "duracao_nome": "15 minutos", "duracao_horas": 0.25, "preco": 150},
    {"nome": "Vídeo chamada", "duracao_nome": "30 minutos", "duracao_horas": 0.5, "preco": 300},
    {"nome": "Vídeo chamada", "duracao_nome": "45 minutos", "duracao_horas": 0.75, "preco": 450},
    {"nome": "Vídeo chamada", "duracao_nome": "60 minutos", "duracao_horas": 1, "preco": 600},
]

FETICHES_ATO_E_COMPOSICAO: list[dict[str, Any]] = [
    {"nome": "Inversão", "preco": 1, "cobra_por_pessoa": False},
    {"nome": "Acompanhante dele — mulher", "preco": 1, "cobra_por_pessoa": True},
]

# Dois programas com 1h de preços DIFERENTES: aí o extra varia de linha pra linha e a coluna
# "Extra" volta (é o único caso em que ela ainda faz sentido).
PROGRAMAS_DOIS_NIVEIS: list[dict[str, Any]] = [
    {"nome": "Normal", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 400},
    {"nome": "Completo", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 600},
]

# preco None = incluso; preenchido = pago. O `1` é o sentinel de flag que o painel grava hoje
# (`_PRECO_PAGO_SENTINEL`) — logo estes fetiches são "pagos SEM preço cadastrado" e caem no
# fallback derivado do pacote (ADR-0030). O regime de preço cadastrado tem fixture própria abaixo.
# cobra_por_pessoa: False = ato; True = COMPOSIÇÃO (quem acompanha quem). Desde 11/08/2026 o
# catálogo tem um item por composição — o nome aqui é o do rótulo real do painel.
FETICHES: list[dict[str, Any]] = [
    {"nome": "Beijo na boca", "preco": None, "cobra_por_pessoa": False},
    {"nome": "Inversão", "preco": 1, "cobra_por_pessoa": False},
    {"nome": "Acompanhante dele — mulher", "preco": 1, "cobra_por_pessoa": True},
]

# Cadastro COM preço por fetiche (decisão de produto 11/08/2026): o número do painel é o extra.
# Tabela do cenário `fora_cardapio` do diagnóstico de 11/08 — Encontro 400/1h e 700/2h.
PROGRAMAS_ENCONTRO: list[dict[str, Any]] = [
    {"nome": "Encontro", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 400},
    {"nome": "Encontro", "duracao_nome": "2 horas", "duracao_horas": 2, "preco": 700},
]

FETICHES_COM_PRECO: list[dict[str, Any]] = [
    {"nome": "Beijo na boca", "preco": None, "cobra_por_pessoa": False},
    {"nome": "Inversão", "preco": 350, "cobra_por_pessoa": False},
    {"nome": "Chuva dourada", "preco": 350, "cobra_por_pessoa": False},
    {"nome": "Fisting", "preco": 500, "cobra_por_pessoa": False},
]


def test_identidade_inclui_nome_e_idade() -> None:
    txt = render_identidade(CARIOCA)
    assert "Bia" in txt
    assert "26" in txt


def test_endereco_nunca_renderiza_no_bp_modelo() -> None:
    # Gate estrutural (análise prod 22/07): o ponto de encontro saiu do BP_MODELO — só entra via
    # <local_de_encontro> no contexto dinâmico, a partir de Qualificado. A região (1º contato)
    # continua aqui; endereço/ponto de encontro, nunca.
    txt = render_identidade(CARIOCA)
    assert "Barra da Tijuca" in txt  # região segue no BP_MODELO
    assert "ponto de encontro" not in txt
    assert "Endereço" not in txt
    assert "None" not in render_identidade(ESTRANGEIRA)


def test_programas_tabela_uma_linha_por_combinacao() -> None:
    # gotcha do for-loop grudado (M1-T2): cada combinação em SUA PRÓPRIA linha de tabela.
    txt = render_programas(PROGRAMAS)
    linhas_dados = [ln for ln in txt.splitlines() if ln.startswith("| ") and "R$" in ln]
    assert len(linhas_dados) == 3
    assert "Programa Completo" in txt
    assert "1 hora" in txt
    # filtro `brl` (persona.py): persona exige R$1.500 (sem espaço, ponto como separador).
    assert "R$2.500" in txt


def test_fetiches_lista_extra_e_incluso() -> None:
    txt = render_fetiches(FETICHES, PROGRAMAS)
    assert "Beijo na boca" in txt
    assert "Inclusos" in txt  # preco None
    assert "Inversão" in txt
    # Ato pago sem preço cadastrado (ADR-0038): o extra é a 1h DO MESMO programa — +R$800 na
    # Massagem, na 1h e na 2h. Colunas de total prontas, uma para 1 e outra para 2 fetiches.
    assert "cada fetiche soma +R$800, o valor da sua 1h" in txt
    assert "| Pacote | +1 fetiche | +2 fetiches |" in txt
    assert "| Massagem Relaxante (1 hora) | R$1.600 | R$2.400 |" in txt
    assert "| Massagem Relaxante (2 horas) | R$2.300 | R$3.100 |" in txt  # 1500 + 800 (+800)


def test_programa_sem_linha_de_uma_hora_nao_vira_linha_de_ato() -> None:
    # Fail-closed do ADR-0038: o extra É a uma hora. O Completo só existe na 2h, então não há de
    # onde derivar — a linha some da tabela de atos em vez de sair com um número inventado (o
    # preço-hora dava +R$1.250 ali). O pacote continua vendável; o que não existe é o extra.
    txt = render_fetiches(FETICHES, PROGRAMAS)
    assert "| Programa Completo (2 horas) | R$" not in txt
    assert "R$3.750" not in txt  # o total do preço-hora não pode reaparecer


def test_fetiches_catarina_e_a_tabela_do_dono_do_produto() -> None:
    # Os números ditados em 11/08/2026: +R$400 fixo (a 1h dela) em qualquer duração, e a linha de
    # 30 minutos fora de todas as tabelas.
    txt = render_fetiches(FETICHES_CATARINA, PROGRAMAS_CATARINA)
    assert "Inversão: cada fetiche soma +R$400, o valor da sua 1h." in txt
    assert "| Normal (1 hora) | R$800 | R$1.200 |" in txt
    assert "| Normal (2 horas) | R$1.200 | R$1.600 |" in txt
    assert "| Normal (3 horas) | R$1.400 | R$1.800 |" in txt
    assert "| Normal (Pernoite) | R$2.400 | R$2.800 |" in txt
    assert "| Normal (30 minutos) |" not in txt
    # A conduta de upsell do pacote curto aponta a MENOR linha elegível, com o total da tabela.
    assert "Pacote de menos de 1h (Normal (30 minutos)) não leva fetiche pago" in txt
    assert "a partir de 1 hora" in txt
    assert "Fica 800 com ele rs" in txt


def test_fetiches_avisa_que_o_extra_desce_com_a_negociacao() -> None:
    # O extra acompanha o PATAMAR do pacote (ADR-0038). O bloco por-modelo é estático (tabela
    # cheia), então ele diz a regra e aponta NOMINALMENTE o bloco do turno que traz o total já
    # somado (<servico_em_pauta>, foco_do_turno.md.j2) — nunca manda calcular.
    txt = render_fetiches(FETICHES_CATARINA, PROGRAMAS_CATARINA)
    assert "o extra desce junto" in txt
    assert "MESMO patamar do pacote" in txt
    assert "<servico_em_pauta>" in txt
    assert "sem recalcular de cabeça" in txt


def test_video_chamada_nao_carrega_fetiche_pago_em_secao_nenhuma() -> None:
    # Exclusão ORTOGONAL à da duração: a chamada de 60min tem `horas = 1` e passaria no filtro de
    # duração. Fetiche pago é de programa PRESENCIAL (ADR-0021) — ela sai da tabela de atos, da
    # seção "Por pessoa" e da nota de pacote curto (que apontaria "a partir de 1 hora" para a
    # chamada). O presencial de 1h continua lá, com o extra dele.
    txt = render_fetiches(FETICHES_ATO_E_COMPOSICAO, PROGRAMAS_COM_VIDEO)
    assert "chamada" not in txt.lower()
    assert "R$1.000" not in txt  # 600 + 400, o total que a linha de 60min produziria
    assert "R$600" not in txt  # nem o preço dela como base de nada
    assert "Inversão: cada fetiche soma +R$400, o valor da sua 1h." in txt
    assert "| Normal (1 hora) | R$800 | R$1.200 |" in txt  # presencial intacto
    por_pessoa = txt.split("Por pessoa")[1]
    assert "| Normal (1 hora) | R$800 |" in por_pessoa  # 400 (pacote) + 400 (a 1h dela)
    # ADR-0039: a prosa da seção NEGA o regime que morreu, em vez de afirmá-lo.
    assert "o pacote NÃO dobra" in por_pessoa
    assert "DOBRA o pacote" not in txt
    # Só a vídeo chamada é curta: sem pacote curto PRESENCIAL, a conduta de upsell não renderiza.
    assert "não leva fetiche pago" not in txt


def test_extras_diferentes_por_programa_mantem_a_coluna_extra() -> None:
    # Normal 1h a 400 e Completo 1h a 600: o extra varia por PROGRAMA (nunca por duração), e aí
    # o cabeçalho não pode nomear um número só.
    txt = render_fetiches(FETICHES_CATARINA, PROGRAMAS_DOIS_NIVEIS)
    assert "cada fetiche soma o valor da 1h DO MESMO programa" in txt
    assert "| Pacote | Extra | +1 fetiche | +2 fetiches |" in txt
    assert "| Normal (1 hora) | +R$400 | R$800 | R$1.200 |" in txt
    assert "| Completo (1 hora) | +R$600 | R$1.200 | R$1.800 |" in txt


def test_fetiches_por_pessoa_soma_o_mesmo_extra_dos_atos() -> None:
    # ADR-0039: composição (cobra_por_pessoa=True) mantém a SEÇÃO própria — a coluna é o total
    # para os dois, não "+2 fetiches" — mas a CONTA é a dos atos: a 1h do mesmo programa.
    txt = render_fetiches(FETICHES, PROGRAMAS)
    por_pessoa = txt.split("Por pessoa")[1]
    assert "Acompanhante dele — mulher" in por_pessoa
    # Massagem Relaxante: 1h a 800 (a linha de 1h dela) -> extra fixo de +R$800.
    assert "| Massagem Relaxante (1 hora) | R$1.600 |" in por_pessoa  # 800 + 800
    assert "| Massagem Relaxante (2 horas) | R$2.300 |" in por_pessoa  # 1500 + 800
    # O dobro do pacote não é mais total de nada.
    assert "R$3.000" not in txt  # 1500 * 2
    assert "R$5.000" not in txt  # 2500 * 2
    # Programa sem linha de 1h agora some da seção "Por pessoa" TAMBÉM (o regime velho dobrava o
    # pacote e não dependia da 1h; o novo depende, e o fail-closed do ADR-0038 alcança os dois).
    assert "Programa Completo" not in por_pessoa


def test_fetiches_pago_ignora_sentinel_de_flag() -> None:
    # O `1` de `f.preco` é o sentinel que o painel grava só para dizer "pago" — nunca um extra de
    # R$1. Cai no fallback derivado (ADR-0030), como o prod inteiro hoje.
    txt = render_fetiches(FETICHES, PROGRAMAS)
    assert "+R$1 " not in txt
    assert "+R$1\n" not in txt
    assert "+R$1," not in txt


def test_fetiches_preco_cadastrado_e_o_extra_fixo() -> None:
    # Decisão 11/08/2026: com preço no cadastro, o extra é ele — o mesmo em qualquer pacote (o
    # regime derivado dava +R$400 na 1h e +R$350 na 2h, e a IA cotou "800 a 1h" onde o cliente
    # esperava 750). Fetiches com o mesmo extra dividem UMA tabela; extra diferente, tabela própria.
    txt = render_fetiches(FETICHES_COM_PRECO, PROGRAMAS_ENCONTRO)
    assert "Inversão, Chuva dourada: cada fetiche soma +R$350, o mesmo em qualquer pacote." in txt
    assert "| Encontro (1 hora) | R$750 | R$1.100 |" in txt
    assert "| Encontro (2 horas) | R$1.050 | R$1.400 |" in txt
    assert "Fisting: cada fetiche soma +R$500, o mesmo em qualquer pacote." in txt
    assert "| Encontro (1 hora) | R$900 | R$1.400 |" in txt
    # Extra fixo não tem coluna "Extra" por pacote: só o total muda de linha pra linha.
    assert "| Pacote | +1 fetiche | +2 fetiches |" in txt
    assert "| Pacote | Extra |" not in txt


def test_fetiches_cabecalho_nao_promete_valor_igual_entre_pacotes() -> None:
    # Achado 10a do diagnóstico 11/08: "cada um soma o MESMO valor no pacote" colado a uma tabela
    # de valores diferentes (+400/+350) leu-se como "o mesmo entre pacotes" — o cliente contestou
    # a conta e a IA não tinha o que responder. O cabeçalho ambíguo não pode voltar.
    for txt in (
        render_fetiches(FETICHES, PROGRAMAS),
        render_fetiches(FETICHES_COM_PRECO, PROGRAMAS_ENCONTRO),
    ):
        assert "MESMO valor no pacote" not in txt
        assert "vale pra qualquer um" not in txt


def test_fetiches_so_nega_uniformidade_quando_os_extras_diferem() -> None:
    # Revisão de domínio 11/08: "um fetiche não custa o mesmo que outro" é verdade só no regime
    # com preços cadastrados DISTINTOS. No derivado (sentinel/sem preço — quase todo o prod,
    # ADR-0030) o extra é UNIFORME entre os fetiches pagos, e a frase contradizia a tabela logo
    # abaixo dela. Condição = mais de um grupo de extra.
    assert "não custa o mesmo que outro" not in render_fetiches(FETICHES, PROGRAMAS)
    assert "não custa o mesmo que outro" in render_fetiches(FETICHES_COM_PRECO, PROGRAMAS_ENCONTRO)
    # Um preço cadastrado só (grupo único) também é uniforme: nada a negar.
    um_preco = [f for f in FETICHES_COM_PRECO if f["preco"] != 500]
    assert "não custa o mesmo que outro" not in render_fetiches(um_preco, PROGRAMAS_ENCONTRO)


def test_fetiches_tem_defesa_para_confronto_de_conta() -> None:
    # Achado 10b: sem fala de defesa, o modelo só pôde reafirmar seco o número contestado.
    txt = render_fetiches(FETICHES_COM_PRECO, PROGRAMAS_ENCONTRO)
    assert "confrontar" in txt
    assert "sem recalcular de cabeça" in txt
    assert "sem negociar o extra pra baixo" in txt


def test_render_bp3_concatena_identidade_programas_e_fetiches() -> None:
    bp3 = render_bp3(CARIOCA, PROGRAMAS, FETICHES)
    assert "Bia" in bp3
    assert "<programas>" in bp3
    assert "Programa Completo" in bp3
    assert "<fetiches>" in bp3
    assert "Inversão" in bp3


def test_build_system_messages_emite_2_blocos() -> None:
    # BP_GERAL: 2 blocos system (geral + por-modelo), strings puras.
    msgs = build_system_messages(
        geral_md=GERAL,
        modelo_md=render_bp3(CARIOCA, PROGRAMAS, FETICHES),
    )
    assert len(msgs) == 2
    modelo_texto = msgs[1].content
    assert isinstance(modelo_texto, str)  # string pura (formato DeepSeek), não content-blocks
    assert "Bia" in modelo_texto
    assert "26" in modelo_texto
    assert "Programa Completo" in modelo_texto


def test_fetiches_render_byte_identico_entre_modelos_com_mesmo_cadastro() -> None:
    # Ticket 03 (spec 0001-fetiche-calculado): o preço por-programa é calculado no render, não no
    # turno — duas modelos DISTINTAS (identidade diferente) com o MESMO cadastro de
    # fetiches/programas produzem o MESMO bloco <fetiches>, e a mesma modelo produz o mesmo bloco
    # em 2 renders sucessivos (não varia por turno/conversa).
    bloco_a = render_fetiches(FETICHES, PROGRAMAS)
    bloco_b = render_fetiches(FETICHES, PROGRAMAS)
    assert bloco_a == bloco_b

    bp3_carioca = render_bp3(CARIOCA, PROGRAMAS, FETICHES)
    bp3_estrangeira = render_bp3(ESTRANGEIRA, PROGRAMAS, FETICHES)
    fetiches_carioca = bp3_carioca.split("<fetiches>")[1]
    fetiches_estrangeira = bp3_estrangeira.split("<fetiches>")[1]
    assert fetiches_carioca == fetiches_estrangeira


def test_guardrail_bp_geral_byte_identico_entre_modelos_string_pura() -> None:
    # Guard-rail #1 no formato que RODA em prod (string pura, DeepSeek): o cache automático do
    # DeepSeek só dá hit se o BP_GERAL sair byte-idêntico entre modelos. Pega regressão se alguém
    # interpolar dado por-modelo no prefixo geral.
    a = build_system_messages(
        geral_md=GERAL,
        modelo_md=render_bp3(CARIOCA, PROGRAMAS, FETICHES),
    )
    b = build_system_messages(
        geral_md=GERAL,
        modelo_md=render_bp3(ESTRANGEIRA, [], []),
    )
    assert isinstance(a[0].content, str)  # string pura (formato DeepSeek), não content-blocks
    assert a[0].content == b[0].content  # BP_GERAL byte-idêntico entre modelos
    assert a[1].content != b[1].content  # BP_MODELO difere por-modelo


def test_cardapio_fechado_renderiza_depois_das_listas() -> None:
    # Rodada 3 (closed-world): o contrato "ausência = não faz" era docstring (só o dev lia);
    # agora é texto que o modelo lê, colado no dado que ele fecha — por isso DEPOIS das listas.
    bp3 = render_bp3(CARIOCA, PROGRAMAS, FETICHES)
    assert "<cardapio_fechado>" in bp3
    assert bp3.index("<cardapio_fechado>") > bp3.index("<fetiches>")
    assert "NUNCA afirma fazer" in bp3
    # proibição sem fala de substituição é o anti-padrão do incidente #36: a recusa oferece junto.
    assert "<fora_do_cardapio>" in bp3


def test_cardapio_fechado_byte_identico_entre_modelos() -> None:
    # Bloco estático: byte-idêntico entre modelos e entre renders (pré-req do cache do BP_MODELO).
    a = render_bp3(CARIOCA, PROGRAMAS, FETICHES).split("<cardapio_fechado>")[1]
    b = render_bp3(ESTRANGEIRA, [], []).split("<cardapio_fechado>")[1]
    assert a == b
