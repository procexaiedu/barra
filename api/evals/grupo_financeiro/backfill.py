"""Backfill: o export do grupo importado em MODO GRAVACAO (ticket 03, spec 0006 US 51-53).

O compromisso com prazo da reuniao de 20/08: **agosto 01-17 das oito modelos** calculado a partir
do historico dos grupos. O replay (`replay.py`) ja passa o export inteiro pela PORTA UNICA e ja faz
`ROLLBACK` no fim — ele e avaliacao. Este arquivo e a outra metade: a corrida que **grava**.

Tres coisas o separam do replay, e nenhuma e um modo de impressao:

* **Ele nao monta cenario.** O replay cria modelo, nome de anuncio e grupo para poder medir; o
  backfill escreve num Grupo financeiro que a operacao **ja cadastrou**, achado por JID. Closed
  world do modulo inteiro: quem nao esta cadastrado nao vira venda, e um backfill que criasse
  cadastro estaria inventando de quem e o dinheiro.
* **Ele e MUDO.** `enviar` e um gravador em memoria, nunca a Evolution. As centenas de recibos que
  a porta produziria ("✅ Registrei R$ 700 · Yasmin") sao de um mes vencido: postados hoje, no grupo
  real, com a modelo dentro, sao a metralhadora que o dominio proibe. O que ela teria dito fica no
  relatorio, para conferencia.
* **Ele prova o silencio antes de fechar a transacao.** Ver "O selo do historico", abaixo.

    TEST_DATABASE_URL=... uv run python -m evals.grupo_financeiro.backfill \\
        --export "../WhatsApp Chat - Modelo Yasmin Ruiva_ financeiro 🤑.zip" \\
        --grupo-jid 120363...@g.us --apelido yasmin --ocr --llm     # ensaio (nao grava)
    ... o mesmo comando + --gravar                                   # grava de verdade

Sem `--gravar` a corrida termina em `ROLLBACK`: o ensaio le tudo, escreve tudo, mostra o que daria
e desfaz. E o mesmo desenho do replay, e e o que permite ensaiar o backfill de um grupo real sem
tocar no dinheiro dele.

## Idempotencia (US 53)

`chave_dedup` da mensagem. O export nao traz `evolution_message_id` (o WhatsApp nao exporta id),
entao o id sintetico e `<apelido>:<indice>` (`chat_export.id_da_mensagem`) — deterministico. Rodar
de novo depois de corrigir um bug reprocessa as mesmas linhas, `registrar_mensagem` bate no
`ON CONFLICT` e a porta para em `duplicada` antes de escrever qualquer coisa. Atras dele ainda ha a
`chave_conteudo` da venda, do comprovante e da cobranca — duas barreiras, as duas no banco.

⚠️ **O apelido e obrigatorio e tem que ser unico por export.** `chave_dedup` tem indice unico na
tabela INTEIRA, nao por grupo: dois exports com o mesmo apelido colidem linha a linha e o segundo
grupo entra todo como entrega duplicada, em silencio, sem uma linha de erro.

## O selo do historico (o maior risco deste ticket)

O que o backfill importa e **historico**: soma no saldo e **nao** entra em cobranca. Importar
agosto de oito grupos gera centenas de pendencias legitimas (forma nao dita, bolso nao dito,
comprovante faltando) e a rotina consolidada da manha as cobraria nos grupos reais, com as modelos
dentro, sobre um mes vencido.

O modulo **nao tem coluna de "historico"** — e nao ha uma para inventar aqui: o corte teria que
viver em `repo.vendas_sem_forma_de_pagamento`, em `fechamento.pendencias_da_venda` e em
`rotina.fichas_sem_desfecho`, que sao dominio e migration, nao eval. O que existe e o interruptor
que ja significa exatamente "a IA nao atende este grupo": `grupos_financeiros.ativo`.
`grupos_financeiros_ativos` (a UNICA leitura que a rotina da manha faz para saber quem visitar)
filtra por ele, e `buscar_grupo_cadastrado_por_jid` tambem — inativo e ingestao e fala desligadas.

Entao o modo gravacao **sela**: no fim da importacao, na MESMA transacao, `ativo` vai a `false`. E
verdade sobre o mundo no momento do backfill (a IA ainda nao esta nesses grupos) e nao falsifica
nenhum numero: o saldo e derivado de `modelo_id`, nao do grupo, e continua inteiro no painel.

Depois de selar, o backfill **prova**: pergunta a `grupos_da_rotina` se o grupo ainda seria
visitado e roda `cobrar_pendencias_do_grupo` num SAVEPOINT desfeito, so para imprimir o que ela
DIRIA. Se a prova nao fecha calada, a transacao inteira e descartada — nao se grava um backfill que
acorda a rotina.

⚠️ **A heranca continua la.** No dia em que a operacao reativar o grupo, as pendencias de agosto
voltam a ser cobraveis: o selo e uma pausa, nao um esquecimento. O relatorio imprime a fala que
ficou de heranca justamente para esse dia ser uma decisao, e nao uma surpresa. A solucao duravel e
um corte de data (ou uma coluna) no dominio — fora do escopo deste arquivo.

## Sem vendedor, e isso e o certo (ADR-0048)

Em agosto quem anunciava no grupo era a gestora, nao o telefonista. O export nao traz o telefone de
ninguem, e o resolver de vendedor e closed-world por `vendedores.whatsapp_jid`, casando o JID
literalmente — entao o autor das linhas de gestora entra como `chat_export.JID_DO_HISTORICO`, um
JID de dominio reservado que nao pode casar com cadastro nenhum. Venda importada nasce sem
vendedor e nao gera comissao retroativa. Comissao de agosto, se o dono quiser, e atribuicao manual
no painel.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from barra.agente_financeiro.comprovante import LerComprovante, leitor_de_comprovante
from barra.agente_financeiro.leitura import LerIntencao, leitor_de_intencao
from barra.agente_financeiro.porta import ResultadoDaPorta, processar_evento_do_grupo
from barra.agente_financeiro.rotina import cobrar_pendencias_do_grupo, grupos_da_rotina
from barra.agente_financeiro.transcricao import TranscreverAudio, ouvinte_do_grupo
from barra.dominio.grupo_financeiro.modelos import GrupoFinanceiro
from barra.dominio.grupo_financeiro.repo import buscar_grupo_por_jid, criar_temporada
from barra.settings import get_settings
from evals.grupo_financeiro.chat_export import BRT, mensagem_do_export
from evals.grupo_financeiro.replay import (
    ZIP_DO_EXPORT,
    Falas,
    carregar_export,
    linha_do_saldo,
    razao_da_modelo,
)

Modo = Literal["ensaio", "gravacao"]
"""`ensaio` = escreve e desfaz (o default, e o mesmo desenho do replay); `gravacao` = commita."""

Desfecho = Literal["gravar", "descartar"]


@dataclass(frozen=True)
class ProvaDaManha:
    """O que a rotina da manha faria com este grupo DEPOIS do import — medido, nao prometido.

    Nao e um teste: e a condicao de commit do modo gravacao. A pergunta que ela responde e a unica
    que importa no dia do backfill — "isto vai falar no grupo real amanha de manha?" — e ela e
    respondida contra o banco ja escrito, com a rotina de verdade, e nao por raciocinio.
    """

    grupo_jid: str
    visitada_pela_rotina: bool
    """O grupo ainda aparece em `grupos_da_rotina`? `False` = selado (ou ja inativo)."""
    status: str | None = None
    """O `StatusDaRotina` que a rotina devolveu no ensaio dentro do SAVEPOINT."""
    fala: str | None = None
    """O que ela DIRIA se visitasse — a heranca de agosto, impressa para o dia da reativacao."""

    @property
    def calada(self) -> bool:
        """Amanha de manha, este grupo recebe mensagem? `True` = nao recebe nenhuma."""
        return not self.visitada_pela_rotina or self.fala is None


@dataclass(frozen=True)
class ResultadoDoBackfill:
    """O observavel de UMA corrida de backfill sobre UM export — como `ResultadoDaPorta`."""

    grupo_jid: str
    apelido: str
    modo: Modo
    linhas: int = 0
    """Linhas do `_chat.txt`, inclusive as que nem chegam a porta (sistema, apagada, vazia)."""
    entregues: int = 0
    """Mensagens que entraram pela porta unica."""
    registradas: int = 0
    duplicadas: int = 0
    """As que a `chave_dedup` barrou — na segunda corrida, isto tende a `entregues`."""
    ignoradas: int = 0
    vendas: int = 0
    pagamentos: int = 0
    correcoes: int = 0
    anuladas: int = 0
    cobrancas: int = 0
    comprovantes: int = 0
    cadastros: int = 0
    falas_suprimidas: tuple[str, ...] = ()
    """O que a porta teria postado no grupo e o backfill engoliu. Conferencia, nunca entrega."""
    selado: bool = False
    prova: ProvaDaManha | None = None
    desfecho: Desfecho = "descartar"
    temporada_id: UUID | None = None


def decidir(*, modo: Modo, prova: ProvaDaManha) -> Desfecho:
    """Commita ou descarta. UNICO lugar que decide, e por isso e uma funcao pura e testavel.

    Duas regras, nesta ordem:

    * **Ensaio nunca grava.** Nem com a manha calada: o modo avaliacao existe para poder rodar o
      backfill de um grupo real sem tocar no dinheiro dele, e um ensaio que grava "porque estava
      tudo certo" e um modo que nao existe.
    * **Gravacao so grava com a manha calada.** Se a rotina falaria, a transacao inteira vai fora:
      centenas de pendencias de um mes vencido cobradas no grupo real e o maior risco deste
      ticket, e ele nao e mitigado por um aviso no fim do log.
    """
    if modo == "ensaio":
        return "descartar"
    return "gravar" if prova.calada else "descartar"


async def selar_como_historico(conn: psycopg.AsyncConnection[Any], grupo: GrupoFinanceiro) -> bool:
    """Desliga a IA neste grupo: `ativo = false`. Devolve `False` se ele ja estava desligado.

    O selo do historico. Nao ha coluna de "importado" no modulo, e `ativo` e o interruptor que ja
    significa a coisa certa — `grupos_financeiros_ativos` (a lista que a rotina da manha visita) e
    `buscar_grupo_cadastrado_por_jid` filtram por ele.

    ⚠️ Ele desliga a INGESTAO junto: mensagem que chegar neste grupo depois do selo e ignorada como
    grupo nao cadastrado. E o certo enquanto a IA nao esta no grupo (o caso do backfill de agosto),
    e e por isso que reativar tem que ser um gesto humano no painel, com o relatorio da heranca na
    mao.
    """
    cur = await conn.execute(
        """
        UPDATE barravips.grupos_financeiros
           SET ativo = false
         WHERE id = %s AND ativo
        RETURNING id
        """,
        (grupo.id,),
    )
    return await cur.fetchone() is not None


async def provar_a_manha(
    conn: psycopg.AsyncConnection[Any], grupo: GrupoFinanceiro, *, agora: datetime
) -> ProvaDaManha:
    """Roda a rotina da manha de verdade, num SAVEPOINT desfeito, e conta o que ela faria.

    Duas medidas, e as duas sao necessarias:

    * `visitada_pela_rotina` sai de `grupos_da_rotina` — a MESMA lista do worker. E o que o selo
      muda, e e a resposta que decide o commit.
    * `fala` sai de `cobrar_pendencias_do_grupo` chamada com `enviar=None`, dentro de um savepoint
      que e sempre desfeito. Ela e medida INCLUSIVE quando o grupo ja esta selado, porque e a
      heranca: e exatamente esta mensagem que voltara a existir no dia em que alguem reativar.

    O savepoint nao e paranoia: a rotina ESCREVE (ela reserva a fala do dia em
    `grupo_financeiro_mensagens` para nao falar duas vezes). Sem desfazer, o backfill gravaria uma
    reserva de uma fala que ninguem disse, e a rotina de verdade daquele dia ficaria muda achando
    que ja tinha falado.
    """
    visitada = any(outro.id == grupo.id for outro in await grupos_da_rotina(conn))
    status: str | None = None
    fala: str | None = None
    async with conn.transaction(force_rollback=True):
        resultado = await cobrar_pendencias_do_grupo(conn, grupo, agora=agora, enviar=None)
        status, fala = resultado.status, resultado.fala
    return ProvaDaManha(
        grupo_jid=grupo.jid, visitada_pela_rotina=visitada, status=status, fala=fala
    )


@dataclass
class _Contagem:
    """Acumulador da corrida — mutavel de proposito, virado em `ResultadoDoBackfill` no fim."""

    entregues: int = 0
    registradas: int = 0
    duplicadas: int = 0
    ignoradas: int = 0
    vendas: int = 0
    pagamentos: int = 0
    correcoes: int = 0
    anuladas: int = 0
    cobrancas: int = 0
    comprovantes: int = 0
    cadastros: int = 0
    falas: list[str] = field(default_factory=list)

    def somar(self, resultado: ResultadoDaPorta) -> None:
        self.entregues += 1
        if resultado.status == "registrada":
            self.registradas += 1
        elif resultado.status == "duplicada":
            self.duplicadas += 1
        elif resultado.status in ("ignorado", "grupo_nao_cadastrado"):
            self.ignoradas += 1
        self.vendas += len(resultado.vendas)
        self.pagamentos += len(resultado.pagamentos)
        self.correcoes += len(resultado.correcoes)
        self.anuladas += len(resultado.anuladas)
        self.cobrancas += len(resultado.cobrancas)
        self.comprovantes += 1 if resultado.comprovante_id else 0
        self.cadastros += 1 if resultado.cadastro else 0


async def importar(
    conn: psycopg.AsyncConnection[Any],
    *,
    export: Path,
    grupo_jid: str,
    apelido: str,
    modo: Modo = "ensaio",
    gestoras: Sequence[str] | None = None,
    ler_comprovante: LerComprovante | None = None,
    ler_intencao: LerIntencao | None = None,
    transcrever: TranscreverAudio | None = None,
    selar: bool = True,
    verboso: bool = True,
) -> ResultadoDoBackfill:
    """Passa o export inteiro pela porta unica, sela o grupo e prova a manha. NAO commita.

    Quem commita e `rodar` (ou o teste): esta funcao deixa a transacao aberta de proposito, porque
    `desfecho` e a decisao do chamador e porque o ensaio precisa poder desfazer tudo.

    A ordem importa: importar -> selar -> provar. Provar antes do selo mediria um grupo que ainda
    seria visitado e reprovaria toda corrida; selar depois da prova gravaria uma prova que nao
    descreve o estado gravado.
    """
    linhas, anexos, roteiro = carregar_export(export)
    # ⚠️ O `.zip` do WhatsApp nao carrega roteiro nenhum, e `carregar_export` devolve o da Yasmin
    # como default do replay. Para qualquer OUTRO grupo, quem manda no grupo tem que vir de fora
    # (`--gestoras`): com a lista errada, TODA mensagem do export vira "a modelo falou" e a tranca
    # da chave Pix (ticket 12) e importada ao contrario, calada.
    quem_manda = tuple(gestoras) if gestoras is not None else roteiro.gestoras
    grupo = await buscar_grupo_por_jid(conn, grupo_jid)
    if grupo is None:
        raise ValueError(
            f"grupo {grupo_jid} nao esta cadastrado (ou esta inativo): o backfill nao cria cadastro"
        )

    falas = Falas()
    contagem = _Contagem()
    # O numero da modelo vem do CADASTRO, nunca do roteiro do export: e ele que decide se "a chave
    # e a minha" foi dito por ela ou por um gestor (ticket 12), e o cadastro e a verdade do
    # sistema. Sem numero cadastrado, todo autor cai como terceiro — o lado seguro.
    numero = grupo.numero_modelo
    for linha in linhas:
        if linha.sistema or linha.apagada or linha.vazia:
            continue
        resultado = await processar_evento_do_grupo(
            conn,
            mensagem_do_export(
                linha,
                grupo_jid=grupo.jid,
                gestoras=quem_manda,
                numero_da_modelo=numero,
                anexos=anexos,
                apelido=apelido,
            ),
            enviar=falas,
            transcrever=transcrever,
            ler_comprovante=ler_comprovante,
            ler_intencao=ler_intencao,
        )
        contagem.somar(resultado)
        for dita in falas.drenar():
            contagem.falas.append(dita)
        if verboso and resultado.status == "registrada" and resultado.vendas:
            print(f"[{linha.indice:03d}] {linha.autor}: venda x{len(resultado.vendas)}")

    selado = await selar_como_historico(conn, grupo) if selar else False
    prova = await provar_a_manha(conn, grupo, agora=manha_seguinte(linhas[-1].quando))
    return ResultadoDoBackfill(
        grupo_jid=grupo.jid,
        apelido=apelido,
        modo=modo,
        linhas=len(linhas),
        entregues=contagem.entregues,
        registradas=contagem.registradas,
        duplicadas=contagem.duplicadas,
        ignoradas=contagem.ignoradas,
        vendas=contagem.vendas,
        pagamentos=contagem.pagamentos,
        correcoes=contagem.correcoes,
        anuladas=contagem.anuladas,
        cobrancas=contagem.cobrancas,
        comprovantes=contagem.comprovantes,
        cadastros=contagem.cadastros,
        falas_suprimidas=tuple(contagem.falas),
        selado=selado,
        prova=prova,
        desfecho=decidir(modo=modo, prova=prova),
    )


def manha_seguinte(ultima: datetime) -> datetime:
    """08:00 BRT do dia seguinte a ultima mensagem do export — a manha que a prova simula.

    Relativa ao export, e nao a hoje, pelo mesmo motivo do replay: com data cravada, um export de
    outra semana mediria "silencio" so porque a manha simulada caiu antes das vendas.
    """
    manha = (ultima + BRT).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return manha - BRT


def imprimir(resultado: ResultadoDoBackfill) -> None:
    """O relatorio da corrida. Curto: quem le isto esta decidindo se commita oito grupos."""
    print(f"\n# Backfill — {resultado.grupo_jid} ({resultado.apelido}) — modo {resultado.modo}\n")
    print(
        f"  linhas={resultado.linhas} entregues={resultado.entregues} "
        f"registradas={resultado.registradas} duplicadas={resultado.duplicadas} "
        f"ignoradas={resultado.ignoradas}"
    )
    print(
        f"  vendas={resultado.vendas} pagamentos={resultado.pagamentos} "
        f"correcoes={resultado.correcoes} anuladas={resultado.anuladas} "
        f"cobrancas={resultado.cobrancas} comprovantes={resultado.comprovantes} "
        f"cadastros={resultado.cadastros}"
    )
    print(
        f"\n## Falas SUPRIMIDAS (o que a porta postaria ao vivo): {len(resultado.falas_suprimidas)}"
    )
    for dita in resultado.falas_suprimidas[:5]:
        print(f"  🤖 {dita.splitlines()[0]}")
    if len(resultado.falas_suprimidas) > 5:
        print(f"  … e mais {len(resultado.falas_suprimidas) - 5}")

    prova = resultado.prova
    print("\n## Selo do historico")
    print(
        f"  grupo selado agora: {'sim' if resultado.selado else 'nao (ja estava, ou --sem-selo)'}"
    )
    if prova is not None:
        print(f"  a rotina visitaria este grupo: {'SIM' if prova.visitada_pela_rotina else 'nao'}")
        print(f"  a manha seguinte fica: {'CALADA' if prova.calada else 'FALANDO'}")
        if prova.fala:
            print("  heranca (o que voltaria a ser cobrado se alguem reativar o grupo):")
            for pedaco in prova.fala.split("\n"):
                print(f"    🤖 {pedaco}")
    print(f"\n## Desfecho: {resultado.desfecho.upper()}")


async def rodar(
    *,
    export: Path,
    grupo_jid: str,
    apelido: str,
    gravar: bool,
    com_ocr: bool,
    com_llm: bool,
    selar: bool,
    gestoras: Sequence[str] | None,
    temporada: tuple[str, date, date] | None,
) -> int:
    url = _url_do_banco(gravar=gravar)
    if url is None:
        return 2
    settings = get_settings()
    ler_comprovante = leitor_de_comprovante(settings) if com_ocr else None
    if com_ocr and ler_comprovante is None:
        print("--ocr pedido, mas OPENROUTER_API_KEY nao esta no ambiente.", file=sys.stderr)
        return 2
    ler_intencao = leitor_de_intencao(settings) if com_llm else None
    if com_llm and ler_intencao is None:
        print("--llm pedido, mas DEEPSEEK_API_KEY nao esta no ambiente.", file=sys.stderr)
        return 2
    transcrever = ouvinte_do_grupo(settings) if com_llm else None

    conn = await psycopg.AsyncConnection.connect(
        url, autocommit=False, row_factory=dict_row, prepare_threshold=None
    )
    try:
        modo: Modo = "gravacao" if gravar else "ensaio"
        resultado = await importar(
            conn,
            export=export,
            grupo_jid=grupo_jid,
            apelido=apelido,
            modo=modo,
            ler_comprovante=ler_comprovante,
            ler_intencao=ler_intencao,
            transcrever=transcrever,
            selar=selar,
            gestoras=gestoras,
        )
        grupo = await buscar_grupo_por_jid(conn, grupo_jid)
        modelo_id = grupo.modelo_id if grupo is not None else None
        if modelo_id is None:
            # O selo ja tirou o grupo de `buscar_grupo_por_jid` (ela filtra `ativo`). Relemos a
            # modelo pelo caminho de escrita, que e o unico que ainda a enxerga.
            modelo_id = await _modelo_do_grupo(conn, grupo_jid)

        temporada_id: UUID | None = None
        if temporada is not None and modelo_id is not None:
            cidade, inicio, fim = temporada
            aberta = await criar_temporada(
                conn,
                modelo_id=modelo_id,
                cidade=cidade,
                data_inicio=inicio,
                data_fim=fim,
                observacao=f"aberta pelo backfill do export {resultado.apelido}",
            )
            temporada_id = aberta.id

        imprimir(resultado)
        if modelo_id is not None:
            recorte = (temporada[1], temporada[2]) if temporada else (None, None)
            razao = await razao_da_modelo(conn, modelo_id, inicio=recorte[0], fim=recorte[1])
            print("\n## Razao da modelo (o saldo que o backfill produziu)")
            print(linha_do_saldo(resultado.apelido, razao))
            if temporada_id is not None:
                print(f"  temporada aberta: {temporada_id}")

        if resultado.desfecho == "gravar":
            await conn.commit()
            print("\nCOMMIT — o historico esta no banco e o grupo esta selado.")
            return 0
        await conn.rollback()
        if resultado.modo == "gravacao":
            print(
                "\nROLLBACK — a manha seguinte NAO ficou calada. Nada foi gravado.",
                file=sys.stderr,
            )
            return 3
        print("\nROLLBACK — ensaio (use --gravar para valer).")
        return 0
    finally:
        if not conn.closed:
            await conn.rollback()
            await conn.close()


async def _modelo_do_grupo(conn: psycopg.AsyncConnection[Any], jid: str) -> UUID | None:
    """A modelo do grupo IGNORANDO `ativo` — a unica leitura que enxerga um grupo ja selado."""
    cur = await conn.execute(
        "SELECT modelo_id FROM barravips.grupos_financeiros WHERE jid = %s LIMIT 1", (jid,)
    )
    row = await cur.fetchone()
    if row is None:
        return None
    valor = row["modelo_id"] if isinstance(row, dict) else row[0]
    return valor if isinstance(valor, UUID) else None


def _url_do_banco(*, gravar: bool) -> str | None:
    """`TEST_DATABASE_URL` sempre; `DATABASE_URL` so com `--gravar`, e nomeando qual foi usada.

    O ensaio escreve e desfaz — e escrever-e-desfazer no banco de PRODUCAO por causa de uma
    variavel de ambiente herdada do shell nao e um risco que valha a conveniencia. O backfill de
    verdade e que aponta para producao, e ai o operador digitou `--gravar`.
    """
    teste = os.environ.get("TEST_DATABASE_URL")
    if teste:
        print(f"# banco: TEST_DATABASE_URL ({'gravacao' if gravar else 'ensaio'})")
        return teste
    producao = os.environ.get("DATABASE_URL") if gravar else None
    if producao:
        print("# banco: DATABASE_URL (gravacao)")
        return producao
    print(
        "TEST_DATABASE_URL obrigatorio (DATABASE_URL so e aceita com --gravar).", file=sys.stderr
    )
    return None


def _lista(bruto: str | None) -> tuple[str, ...] | None:
    """`--gestoras "~ Dani,~ Parcerias"` -> a tupla. `None` = usa o roteiro do export."""
    if not bruto:
        return None
    return tuple(p.strip() for p in bruto.split(",") if p.strip())


def temporada_do_argumento(bruto: str | None) -> tuple[str, date, date] | None:
    """`--temporada "Sao Paulo:2026-08-01:2026-08-17"`.

    Opt-in, e nunca automatico: "quem abre temporada e gente, pela tela"
    (`repo.criar_temporada`). O operador que roda o backfill de agosto E gente — mas o backfill
    nao adivinha cidade nem periodo por conta propria.
    """
    if not bruto:
        return None
    cidade, _, resto = bruto.partition(":")
    inicio, _, fim = resto.partition(":")
    if not cidade or not inicio or not fim:
        raise ValueError("--temporada quer 'Cidade:AAAA-MM-DD:AAAA-MM-DD'")
    return cidade.strip(), date.fromisoformat(inicio), date.fromisoformat(fim)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=ZIP_DO_EXPORT, help="zip ou pasta do export")
    parser.add_argument("--grupo-jid", required=True, help="JID do Grupo financeiro ja cadastrado")
    parser.add_argument(
        "--apelido",
        required=True,
        help="namespace dos ids sinteticos — UNICO por export (ver a docstring)",
    )
    parser.add_argument(
        "--gravar", action="store_true", help="commita (default: ensaio + rollback)"
    )
    parser.add_argument("--ocr", action="store_true", help="le os comprovantes de verdade (custa)")
    parser.add_argument("--llm", action="store_true", help="leitor de intencao + audio (custa)")
    parser.add_argument(
        "--sem-selo",
        action="store_true",
        help="nao desliga o grupo no fim (so grava se a rotina ficar calada assim mesmo)",
    )
    parser.add_argument(
        "--gestoras",
        help="nomes de exibicao de quem NAO e a modelo, separados por virgula "
        "(ex.: '~ Dani,~ Parcerias'). Obrigatorio para todo export que nao seja o da Yasmin.",
    )
    parser.add_argument("--temporada", help="'Cidade:AAAA-MM-DD:AAAA-MM-DD' — abre a temporada")
    args = parser.parse_args()
    if not args.export.exists():
        print(f"export nao encontrado: {args.export}", file=sys.stderr)
        return 2
    return asyncio.run(
        rodar(
            export=args.export,
            grupo_jid=args.grupo_jid,
            apelido=args.apelido,
            gravar=args.gravar,
            com_ocr=args.ocr,
            com_llm=args.llm,
            selar=not args.sem_selo,
            gestoras=_lista(args.gestoras),
            temporada=temporada_do_argumento(args.temporada),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
