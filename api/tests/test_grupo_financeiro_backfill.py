"""O backfill do export em modo gravacao (ticket 03, spec 0006 US 51-53) — sem banco.

O que da para afirmar SEM Postgres e, aqui, quase tudo o que importa: a identidade das mensagens
(que e a idempotencia), a autoria (que e a comissao que nao pode retroagir), a midia (que e o OCR),
a triagem barata do social (que e o custo) e a decisao de commitar (que e o risco de acordar a
rotina num grupo real). O que sobra para `needs_db` esta nomeado no fim deste arquivo.

O export REAL (`WhatsApp Chat - Modelo Yasmin Ruiva_ financeiro 🤑.zip`, na raiz do repo) e a
fixture: ele e a unica semana de grupo verdadeira que o projeto tem, e ler o zip nao custa nem
banco nem credito.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from evals.grupo_financeiro.backfill import (
    ProvaDaManha,
    decidir,
    manha_seguinte,
    temporada_do_argumento,
)
from evals.grupo_financeiro.chat_export import (
    JID_DO_HISTORICO,
    LinhaDoExport,
    apelido_do_export,
    id_da_mensagem,
    mensagem_do_export,
)
from evals.grupo_financeiro.replay import ROTEIRO_DA_YASMIN, ZIP_DO_EXPORT, carregar_export

from barra.dominio.grupo_financeiro.anuncio import parece_anuncio_de_venda
from barra.dominio.grupo_financeiro.dados_cadastrais import autor_e_a_modelo
from barra.dominio.grupo_financeiro.modelos import MensagemDoGrupo
from barra.dominio.grupo_financeiro.repo import chave_do_jid

NUMERO_DA_YASMIN = ROTEIRO_DA_YASMIN.numero_da_modelo
GRUPO = "120363000000000001@g.us"


@pytest.fixture(scope="module")
def export_real() -> tuple[list[LinhaDoExport], dict[str, bytes]]:
    if not ZIP_DO_EXPORT.exists():  # pragma: no cover - o zip e versionado na raiz do repo
        pytest.skip(f"export real ausente: {ZIP_DO_EXPORT}")
    linhas, anexos, _ = carregar_export(ZIP_DO_EXPORT)
    return linhas, anexos


def _mensagens(
    linhas: list[LinhaDoExport],
    anexos: dict[str, bytes],
    *,
    apelido: str = "yasmin",
    numero: str | None = NUMERO_DA_YASMIN,
    grupo_jid: str = GRUPO,
) -> list[MensagemDoGrupo]:
    return [
        mensagem_do_export(
            linha,
            grupo_jid=grupo_jid,
            gestoras=ROTEIRO_DA_YASMIN.gestoras,
            numero_da_modelo=numero,
            anexos=anexos,
            apelido=apelido,
        )
        for linha in linhas
        if not (linha.sistema or linha.apagada or linha.vazia)
    ]


# --- idempotencia: rodar duas vezes nao cria linha nova (US 53) ---------------------------------


def test_a_segunda_corrida_do_mesmo_export_repete_as_mesmas_chaves_de_entrega(
    export_real: tuple[list[LinhaDoExport], dict[str, bytes]],
) -> None:
    """A idempotencia do backfill E a `chave_dedup`: identica, o `ON CONFLICT` barra a re-escrita.

    Comparar duas LEITURAS do mesmo zip, e nao a mesma lista duas vezes: o que se afirma e que
    nada na construcao da mensagem depende do relogio, de um uuid ou da ordem de um dicionario —
    as tres fontes classicas de um id que "quase" repete.
    """
    linhas, anexos = export_real
    primeira = [m.chave_dedup() for m in _mensagens(linhas, anexos)]
    outras_linhas, outros_anexos, _ = carregar_export(ZIP_DO_EXPORT)
    segunda = [m.chave_dedup() for m in _mensagens(outras_linhas, outros_anexos)]

    assert primeira == segunda
    assert len(set(primeira)) == len(primeira)


def test_dois_exports_diferentes_nao_colidem_na_chave_de_entrega(
    export_real: tuple[list[LinhaDoExport], dict[str, bytes]],
) -> None:
    """O apelido e o que separa oito grupos. Sem ele, o segundo grupo some em silencio.

    `chave_dedup` tem indice unico na tabela INTEIRA (nao por grupo): a mensagem 1 da Yasmin e a
    mensagem 1 da Julia com o mesmo id sintetico produzem a mesma chave, e `registrar_mensagem`
    devolve `None` para a segunda — o grupo inteiro entrando como "entrega duplicada", sem erro
    nenhum em lugar nenhum. Este teste e a barreira contra a regressao para um id global.
    """
    linhas, anexos = export_real
    yasmin = {m.chave_dedup() for m in _mensagens(linhas, anexos, apelido="yasmin")}
    julia = {
        m.chave_dedup()
        for m in _mensagens(linhas, anexos, apelido="julia", grupo_jid="120363000000000002@g.us")
    }

    assert not (yasmin & julia)


def test_o_mesmo_apelido_em_dois_grupos_colide_de_proposito(
    export_real: tuple[list[LinhaDoExport], dict[str, bytes]],
) -> None:
    """A outra metade da afirmacao acima: a colisao existe e e o apelido que a evita.

    Sem este teste, o anterior passaria mesmo se a chave dependesse do `grupo_jid` — e a lição
    ficaria escondida atras de um detalhe que pode mudar.
    """
    linhas, anexos = export_real
    um = {m.chave_dedup() for m in _mensagens(linhas, anexos, apelido="mesmo")}
    outro = {
        m.chave_dedup()
        for m in _mensagens(linhas, anexos, apelido="mesmo", grupo_jid="120363000000000002@g.us")
    }

    assert um == outro


def test_id_da_mensagem_carrega_o_apelido_e_o_indice() -> None:
    assert id_da_mensagem("yasmin", 7) == "yasmin:00007"
    assert apelido_do_export(Path("WhatsApp Chat - Modelo Yasmin Ruiva_ financeiro 🤑.zip")) == (
        "whatsapp-chat-modelo-yasmin-ruiva-financeiro"
    )


# --- autoria: venda importada nasce SEM vendedor (ADR-0048) -------------------------------------


def test_a_gestora_do_export_entra_com_um_jid_que_nenhum_vendedor_pode_ter(
    export_real: tuple[list[LinhaDoExport], dict[str, bytes]],
) -> None:
    """Em agosto quem anunciava era a gestora, e a comissao do telefonista NAO retroage.

    O resolver de vendedor e closed-world por `vendedores.whatsapp_jid` e casa o JID
    literalmente. Um telefone de fantasia aqui — o `5521999999999` que o replay usava — pode estar
    cadastrado e atribuiria comissao retroativa a quem nao vendeu nada. O dominio `.invalid` (RFC
    2606) nao tem a forma de nenhum JID do WhatsApp, entao nao casa nem por acidente.
    """
    linhas, anexos = export_real
    de_gestora = [
        m
        for linha, m in zip(
            [linha for linha in linhas if not (linha.sistema or linha.apagada or linha.vazia)],
            _mensagens(linhas, anexos),
            strict=True,
        )
        if linha.autor in ROTEIRO_DA_YASMIN.gestoras
    ]

    assert de_gestora, "o export real tem linhas de gestora"
    assert {m.autor_jid for m in de_gestora} == {JID_DO_HISTORICO}
    chave = chave_do_jid(JID_DO_HISTORICO)
    assert chave is not None
    assert not chave.endswith(("@s.whatsapp.net", "@lid", "@g.us"))


def test_o_jid_do_historico_nunca_e_a_modelo() -> None:
    """Fail-closed do outro lado: quem posta pelo export nao pode ensinar a chave Pix dela."""
    assert autor_e_a_modelo(JID_DO_HISTORICO, NUMERO_DA_YASMIN) is False


def test_a_modelo_entra_com_o_numero_do_cadastro(
    export_real: tuple[list[LinhaDoExport], dict[str, bytes]],
) -> None:
    """O que NAO e gestora e ela — e o numero tem que ser o do cadastro, senao a tranca da chave
    Pix (ticket 12) e importada ao contrario."""
    linhas, anexos = export_real
    dela = [m for m in _mensagens(linhas, anexos) if m.autor_jid != JID_DO_HISTORICO]

    assert dela, "o export real tem linhas da propria modelo"
    assert {m.autor_jid for m in dela} == {f"{NUMERO_DA_YASMIN}@s.whatsapp.net"}
    assert autor_e_a_modelo(dela[0].autor_jid, NUMERO_DA_YASMIN) is True


def test_sem_numero_cadastrado_todo_autor_cai_como_terceiro(
    export_real: tuple[list[LinhaDoExport], dict[str, bytes]],
) -> None:
    """Grupo cadastrado sem `numero_whatsapp` da modelo: o lado seguro e "nao foi ela"."""
    linhas, anexos = export_real
    mensagens = _mensagens(linhas, anexos, numero=None)

    assert {m.autor_jid for m in mensagens} == {JID_DO_HISTORICO}


# --- midia: o comprovante do zip passa pelo mesmo OCR da producao -------------------------------


def test_a_foto_do_zip_chega_com_os_bytes_para_o_ocr(
    export_real: tuple[list[LinhaDoExport], dict[str, bytes]],
) -> None:
    """Os bytes viajam na mensagem, como o webhook os entrega ao vivo — nao uma URL, nao um path.

    Sem isto o backfill importaria o comprovante como uma mensagem muda e o abate de agosto nunca
    aconteceria: o dinheiro entraria como venda a comprovar para sempre.
    """
    linhas, anexos = export_real
    com_foto = [
        (linha, m)
        for linha, m in zip(
            [linha for linha in linhas if not (linha.sistema or linha.apagada or linha.vazia)],
            _mensagens(linhas, anexos),
            strict=True,
        )
        if linha.tipo == "imagem"
    ]

    assert len(com_foto) == 5, "o export real tem cinco fotos"
    for linha, mensagem in com_foto:
        assert mensagem.tipo == "imagem"
        assert mensagem.imagem is not None
        assert linha.anexo is not None
        assert mensagem.imagem.conteudo == anexos[linha.anexo]
        assert mensagem.imagem.mimetype == "image/jpeg"


def test_sticker_e_video_nao_viram_midia(
    export_real: tuple[list[LinhaDoExport], dict[str, bytes]],
) -> None:
    """Sticker e video sao `outro`: entram como texto vazio (existem no log e nao dizem nada).

    Pagar OCR por um sticker seria o custo que a triagem barata existe para evitar, e um video
    nao tem leitor nenhum neste modulo.
    """
    linhas, anexos = export_real
    outros = [linha for linha in linhas if linha.tipo == "outro"]

    assert len(outros) == 3, "o export real tem um video e dois stickers"
    for linha in outros:
        mensagem = mensagem_do_export(
            linha,
            grupo_jid=GRUPO,
            gestoras=ROTEIRO_DA_YASMIN.gestoras,
            numero_da_modelo=NUMERO_DA_YASMIN,
            anexos=anexos,
            apelido="yasmin",
        )
        assert mensagem.tipo == "texto"
        assert mensagem.imagem is None
        assert mensagem.audio is None


# --- custo: a mensagem social do export continua morrendo na triagem ----------------------------


def test_a_conversa_do_export_nao_custa_extracao(
    export_real: tuple[list[LinhaDoExport], dict[str, bytes]],
) -> None:
    """ "Oi", "Ok", "Foi pix ou din ?", "Site": nada disso pode chegar ao extrator.

    A afirmacao e sobre a SEMANA inteira, com numero: sete anuncios em sessenta e duas linhas. Um
    teste que so verificasse "'Oi' nao e anuncio" passaria com uma triagem que deixasse passar
    tudo o resto — e o custo do backfill de oito grupos e o que estaria em jogo.
    """
    linhas, _ = export_real
    com_texto = [
        linha
        for linha in linhas
        if linha.texto and not (linha.sistema or linha.apagada or linha.vazia)
    ]
    candidatos = [linha for linha in com_texto if parece_anuncio_de_venda(linha.texto)]

    assert len(candidatos) == 7
    for social in ("Oi", "Ok", "Foi pix ou din ?", "Site", "Dinheiro", "Olá bom dia"):
        assert not parece_anuncio_de_venda(social)


# --- a decisao de commitar: o backfill nao pode acordar a rotina --------------------------------

_CALADA = ProvaDaManha(grupo_jid=GRUPO, visitada_pela_rotina=False)
_FALANDO = ProvaDaManha(
    grupo_jid=GRUPO,
    visitada_pela_rotina=True,
    status="cobrou",
    fala="☀️ Bom dia! Ficou pendente:\n❓ R$ 700,00 · 07/08 — foi pix ou dinheiro?",
)


def test_o_ensaio_nunca_grava_nem_com_a_manha_calada() -> None:
    """O modo avaliacao continua existindo e continua nao escrevendo (criterio do ticket).

    Ele nao e "gravacao com sorte ruim": e o modo que permite ensaiar o backfill de um grupo real
    sem tocar no dinheiro dele, e um ensaio que grava porque estava tudo certo e um modo que nao
    existe.
    """
    assert decidir(modo="ensaio", prova=_CALADA) == "descartar"
    assert decidir(modo="ensaio", prova=_FALANDO) == "descartar"


def test_a_gravacao_so_fecha_a_transacao_com_a_manha_calada() -> None:
    """O maior risco do ticket vira condicao de commit, e nao um aviso no fim do log.

    Centenas de pendencias legitimas de um mes vencido cobradas nos grupos reais, com as modelos
    dentro, e o estrago que nao se desfaz depois de a mensagem sair.
    """
    assert decidir(modo="gravacao", prova=_CALADA) == "gravar"
    assert decidir(modo="gravacao", prova=_FALANDO) == "descartar"


def test_a_prova_esta_calada_quando_a_rotina_nao_visita_o_grupo() -> None:
    """O selo (`grupos_financeiros.ativo = false`) tira o grupo de `grupos_da_rotina`.

    A heranca continua medida e impressa (`fala`), porque e ela que volta a existir no dia em que
    alguem reativar o grupo — mas amanha de manha ninguem recebe nada.
    """
    selado = ProvaDaManha(
        grupo_jid=GRUPO, visitada_pela_rotina=False, status="cobrou", fala="☀️ Bom dia! ..."
    )
    assert selado.calada is True
    assert selado.fala


def test_a_prova_nao_esta_calada_quando_a_rotina_visitaria_e_falaria() -> None:
    assert _FALANDO.calada is False
    assert ProvaDaManha(GRUPO, visitada_pela_rotina=True, status="silencio").calada is True


# --- a manha simulada e relativa ao export, nunca a hoje ----------------------------------------


def test_a_manha_da_prova_e_a_do_dia_seguinte_ao_export() -> None:
    """Com data cravada, um export de outra semana mediria "silencio" so porque a manha simulada
    caiu antes das vendas. 08:00 BRT = 11:00 UTC."""
    ultima = datetime(2026, 8, 13, 20, 55, 10, tzinfo=UTC)  # 17:55 BRT de 13/08
    assert manha_seguinte(ultima) == datetime(2026, 8, 14, 11, 0, 0, tzinfo=UTC)


def test_a_manha_da_prova_atravessa_a_virada_do_dia_em_brt() -> None:
    """Mensagem de 00:36 UTC de 14/08 e 21:36 BRT de 13/08: a manha e a de 14/08, nao a de 15/08."""
    ultima = datetime(2026, 8, 14, 0, 36, 0, tzinfo=UTC)
    assert manha_seguinte(ultima) == datetime(2026, 8, 14, 11, 0, 0, tzinfo=UTC)


# --- a temporada e opt-in: o backfill nao adivinha cidade nem periodo ---------------------------


def test_a_temporada_so_existe_quando_o_operador_a_declara() -> None:
    assert temporada_do_argumento(None) is None
    assert temporada_do_argumento("Sao Paulo:2026-08-01:2026-08-17") == (
        "Sao Paulo",
        date(2026, 8, 1),
        date(2026, 8, 17),
    )


def test_temporada_mal_escrita_levanta_em_vez_de_adivinhar() -> None:
    with pytest.raises(ValueError, match="Cidade"):
        temporada_do_argumento("Sao Paulo")


# --- o que este arquivo NAO consegue afirmar ----------------------------------------------------
#
# Precisa de `needs_db` (Postgres com as migrations 20260814* + 20260820* aplicadas), e por isso
# nao esta aqui:
#
# * que o export real gravado produz a temporada da Yasmin com o comprovante de R$ 1.200 e o saldo
#   +600 (`backfill.importar` + `replay.razao_da_modelo`);
# * que a SEGUNDA corrida nao cria nenhuma linha nova (a chave e identica — provado acima —, mas
#   quem a barra e o indice unico do banco);
# * que `selar_como_historico` tira o grupo de `grupos_da_rotina` e que `provar_a_manha` desfaz o
#   savepoint sem deixar a reserva da fala do dia para tras.
