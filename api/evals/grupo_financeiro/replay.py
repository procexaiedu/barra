"""Replay do Grupo financeiro real: o export da Yasmin inteiro pela PORTA UNICA.

E a validacao de produto que a spec 0005 previa ("o protótipo de conversa … é a validação de
produto por cima da mesma porta"). Diferente dos testes `needs_db`, que afirmam UM comportamento
por vez com mensagens escolhidas, aqui entra o grupo INTEIRO na ordem em que ele aconteceu — e o
que se le no fim e o que a gestora leria no WhatsApp se o agente estivesse la naquela semana.

Como rodar (o banco e o mesmo dos testes; o replay abre UMA transacao e faz ROLLBACK no fim):

    TEST_DATABASE_URL=... uv run python -m evals.grupo_financeiro.replay
    TEST_DATABASE_URL=... uv run python -m evals.grupo_financeiro.replay --ocr --llm  # paga
    TEST_DATABASE_URL=... uv run python -m evals.grupo_financeiro.replay \
        --export evals/grupo_financeiro/exports/parceria_e_correcao

Sem `--ocr` as imagens entram com os bytes reais mas SEM leitor: o agente registra a mensagem e
fica calado, que e exatamente o que ele faz em producao quando o provider esta fora. Com `--ocr`
ele le os comprovantes de verdade (OpenRouter) — e ai o replay custa dinheiro, por isso e opt-in.

`--llm` liga o **leitor de intencao** (DeepSeek direto), que e o que a producao usa para entender
a fala do grupo. Sem ele o replay mede a allowlist de fallback: um agente parecido, mais surdo —
e ficar cego para essa diferenca e como o harness fiel ja mordeu este projeto uma vez.

**O cadastro e parte do cenario, nao do agente.** O resolver e closed-world (ADR-0043/spec): quem
nao esta cadastrado nao vira venda. O `Roteiro` de cada export e o que a operacao teria cadastrado
no painel naquela semana — e no export da Yasmin "fran loira", que ela NAO cadastrou, fica de fora
de proposito: e o caso real da user story 20 (o agente pergunta quem e).

**Exports sinteticos** vivem em `exports/<nome>/` (`_chat.txt` + `cenario.json`, mesma gramatica do
iOS). Eles nao substituem o export real — cobrem o que uma semana so nao mostrou (correcao,
anulacao, pagamento coletivo, fechamento parcial, cobranca em aberto).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from barra.agente_financeiro import processar_mensagem_do_grupo
from barra.agente_financeiro.comprovante import leitor_de_comprovante
from barra.agente_financeiro.leitura import leitor_de_intencao
from barra.agente_financeiro.porta import ResultadoDaPorta, fechamento_da_modelo
from barra.agente_financeiro.rotina import cobrar_pendencias_do_grupo
from barra.dominio.grupo_financeiro.modelos import MensagemDoGrupo
from barra.dominio.grupo_financeiro.razao import Razao
from barra.dominio.grupo_financeiro.recibo import formatar_reais
from barra.dominio.grupo_financeiro.repo import (
    buscar_grupo_por_jid,
    cobrancas_abertas_da_modelo,
    deslocamentos_para_o_razao,
    lancamentos_manuais_da_modelo,
    transferencias_para_o_razao,
    vendas_para_o_razao,
)
from barra.dominio.grupo_financeiro.temporada import apurar_o_razao
from barra.settings import get_settings
from evals.grupo_financeiro.chat_export import (
    BRT,
    LinhaDoExport,
    apelido_do_export,
    ler_export,
    mensagem_do_export,
)

RAIZ = Path(__file__).resolve().parents[3]
ZIP_DO_EXPORT = RAIZ / "WhatsApp Chat - Modelo Yasmin Ruiva_ financeiro 🤑.zip"

# --- o roteiro (o que a operacao teria no painel na semana do export) ---------------------------


@dataclass(frozen=True)
class Roteiro:
    """Quem e quem neste export: o cadastro, quem manda no grupo e o destino da casa.

    Vive fora do codigo (`cenario.json` ao lado do `_chat.txt`) porque cada grupo tem o seu, e um
    export novo nao pode exigir edicao deste arquivo — a semana de outra modelo e dado, nao codigo.
    """

    dona: str
    elenco: dict[str, tuple[str, ...]]
    """nome verdadeiro -> Nomes de anuncio cadastrados."""
    gestoras: tuple[str, ...]
    """Quem posta venda e cobranca. O resto dos autores e a modelo (o numero dela)."""
    chave_da_casa: str
    nome_do_grupo: str = "Grupo financeiro"
    numero_da_modelo: str = "5511968544493"
    """O WhatsApp DELA, como o export o escreve. E o que separa "a modelo ditou a chave dela" de
    "um gestor ditou a chave da casa" (ticket 12) — com um numero de fantasia aqui, TODO cadastro
    do replay cairia como `de_terceiro` e o replay mediria uma conduta que a producao nao tem."""
    apelido: str = "export"
    """O namespace dos ids sinteticos das mensagens (`chat_export.id_da_mensagem`).

    Um por EXPORT, nunca compartilhado: `chave_dedup` tem indice unico na tabela inteira, entao
    dois exports com o mesmo apelido colidem linha a linha e o segundo entra como entrega
    duplicada — o grupo inteiro sumindo em silencio. No modo gravacao o apelido e obrigatorio na
    linha de comando justamente por isso."""

    @classmethod
    def de_json(cls, caminho: Path) -> Roteiro:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        return cls(
            dona=bruto["dona"],
            elenco={nome: tuple(ap) for nome, ap in bruto["elenco"].items()},
            gestoras=tuple(bruto["gestoras"]),
            chave_da_casa=bruto["chave_da_casa"],
            nome_do_grupo=bruto.get("nome_do_grupo", "Grupo financeiro"),
            numero_da_modelo=bruto.get("numero_da_modelo", "5511968544493"),
            apelido=bruto.get("apelido") or apelido_do_export(caminho.parent),
        )


ROTEIRO_DA_YASMIN = Roteiro(
    dona="Yasmin",
    elenco={"Yasmin": ("yasmin", "bianca"), "Julia": ("julia", "sophia"), "Alicia": ("alicia",)},
    gestoras=("~ Dani", "~ Parcerias", "~ FEH SANTOS"),
    # A chave que a Parcerias mandou no grupo em 12/08 ("Pix erick"): o destino de FECHAMENTO da
    # casa. Ela esta no proprio export, entao nao ha PII nova aqui — e e o que faz o comprovante
    # de 12/08 cair como destino conhecido.
    chave_da_casa="cb890e5a-c095-4dc5-8309-36babb460e17",
    nome_do_grupo="Modelo Yasmin Ruiva/ financeiro",
    apelido="yasmin",
)
""""fran loira" NAO entra no elenco: no export ela aparece uma vez ("Perfil Alicia/ fran loira") e
nunca foi cadastrada.

**Medido em 16/08, e o resultado nao e o que esta docstring dizia:** o agente NAO pergunta. O
outro token da mesma linha ("Alicia") casa no cadastro, o plano fecha sem falta e a venda inteira
vai para a modelo Alicia — a mulher nova some, em silencio. A pergunta da user story 20 so sai
quando NENHUM token resolve (`rateio._plano_de_uma` -> falta "modelo"); com um conhecido do lado,
`nomes_nao_resolvidos` e carregado e nunca vira pergunta. `exports/perfil_novo_e_cadastro` isola
os dois casos lado a lado."""


@dataclass
class Cenario:
    grupo_jid: str
    modelos: dict[str, UUID]
    roteiro: Roteiro

    @property
    def dona(self) -> UUID:
        return self.modelos[self.roteiro.dona]


async def montar_cenario(
    conn: psycopg.AsyncConnection[dict[str, Any]], roteiro: Roteiro
) -> Cenario:
    """Cria o elenco, os Nomes de anuncio, o Grupo financeiro e a chave da casa."""
    modelos: dict[str, UUID] = {}
    for nome, apelidos in roteiro.elenco.items():
        modelo_id = uuid4()
        modelos[nome] = modelo_id
        await conn.execute(
            """
            INSERT INTO barravips.modelos
                (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
                 percentual_repasse, status)
            VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                    'ativa'::barravips.modelo_status_enum)
            """,
            (
                modelo_id,
                # Nome LIMPO (sem sufixo de unicidade): ele aparece no recibo que o grupo le, e um
                # "Yasmin 853412" no "✅ Registrei" sujaria justamente o que este replay avalia. A
                # unicidade fica no `numero_whatsapp`, que ninguem le.
                nome,
                25,
                # O numero da dona e o do export (e o que faz o cadastro dela funcionar); o das
                # outras continua sintetico, so para nao colidir no UNIQUE.
                roteiro.numero_da_modelo if nome == roteiro.dona else f"replay-{uuid4().hex}",
                600,
                ["interno"],
                Decimal("40"),
            ),
        )
        for apelido in apelidos:
            await conn.execute(
                """
                INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
                VALUES (%s, %s, %s)
                """,
                (modelo_id, apelido, apelido),
            )

    grupo_jid = f"1203634{uuid4().hex[:12]}@g.us"
    await conn.execute(
        "INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome) VALUES (%s,%s,%s,%s)",
        (uuid4(), modelos[roteiro.dona], grupo_jid, roteiro.nome_do_grupo),
    )
    await conn.execute(
        """
        INSERT INTO barravips.chaves_pix_conhecidas (chave, chave_normalizada, titular, descricao)
        VALUES (%s, %s, %s, %s) ON CONFLICT (chave_normalizada) DO NOTHING
        """,
        (
            roteiro.chave_da_casa,
            roteiro.chave_da_casa,
            "Titular da casa",
            "Chave de fechamento do roteiro deste export.",
        ),
    )
    return Cenario(grupo_jid=grupo_jid, modelos=modelos, roteiro=roteiro)


class Falas:
    """O que o agente postaria no grupo, na ordem."""

    def __init__(self) -> None:
        self.desta_mensagem: list[str] = []
        self.todas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.desta_mensagem.append(texto)
        self.todas.append(texto)

    def drenar(self) -> list[str]:
        ditas, self.desta_mensagem = self.desta_mensagem, []
        return ditas


def _mensagem(linha: LinhaDoExport, cenario: Cenario, anexos: dict[str, bytes]) -> MensagemDoGrupo:
    """A traducao mora em `chat_export.mensagem_do_export` — aqui so o cenario do replay entra.

    Um construtor so para o replay e para o backfill: os dois tem que produzir a MESMA identidade
    de mensagem, porque e ela que decide o que ja foi visto (`chave_dedup`).
    """
    return mensagem_do_export(
        linha,
        grupo_jid=cenario.grupo_jid,
        gestoras=cenario.roteiro.gestoras,
        numero_da_modelo=cenario.roteiro.numero_da_modelo,
        anexos=anexos,
        apelido=cenario.roteiro.apelido,
    )



async def razao_da_modelo(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    modelo_id: UUID,
    *,
    inicio: date | None = None,
    fim: date | None = None,
) -> Razao:
    """O saldo COM SINAL da modelo (ticket 02): positivo = a casa deve a ela.

    Cinco leituras e `apurar_o_razao` — o UNICO tradutor de linha-de-tabela em lancamento. Montar
    a lista de lancamentos aqui seria o segundo lugar a fazer isso, e o sintoma de esquecer uma
    classe nova num deles e um saldo que fecha errado sem nenhuma linha de erro.

    `inicio`/`fim` recortam a TEMPORADA e ficam no leitor, nunca no SQL (ADR-0045 §7): o
    comprovante que chega tres dias depois do fim recalcula o saldo em vez de sumir da consulta.
    """
    return apurar_o_razao(
        modelo_id=modelo_id,
        vendas=await vendas_para_o_razao(conn, modelo_id),
        transferencias=await transferencias_para_o_razao(conn, modelo_id),
        cobrancas=await cobrancas_abertas_da_modelo(conn, modelo_id),
        deslocamentos=await deslocamentos_para_o_razao(conn, modelo_id),
        manuais=await lancamentos_manuais_da_modelo(conn, modelo_id),
        inicio=inicio,
        fim=fim,
    )


def linha_do_saldo(nome: str, razao: Razao) -> str:
    """Uma linha de razao para o relatorio — a mesma no replay e no backfill."""
    if razao.saldo > Decimal("0.00"):
        lado = f"a casa deve {formatar_reais(razao.a_casa_deve)}"
    elif razao.saldo < Decimal("0.00"):
        lado = f"ELA deve {formatar_reais(razao.ela_deve)}"
    else:
        lado = "quitado"
    return (
        f"  {nome:8} saldo {formatar_reais(razao.saldo):>12} ({lado}) · "
        f"debitos {formatar_reais(razao.debitos):>12} · creditos {formatar_reais(razao.creditos):>12}"
    )


def _resumo(resultado: ResultadoDaPorta) -> str:
    partes = [f"motivo={resultado.motivo}"]
    if resultado.vendas:
        partes.append(f"vendas={len(resultado.vendas)}")
    if resultado.pagamentos:
        partes.append(f"pagamentos={len(resultado.pagamentos)}")
    if resultado.correcoes:
        partes.append(f"correcoes={len(resultado.correcoes)}")
    if resultado.cobrancas:
        partes.append(f"cobrancas={len(resultado.cobrancas)}")
    if resultado.cobrancas_quitadas:
        partes.append(f"quitadas={len(resultado.cobrancas_quitadas)}")
    if resultado.abatidas:
        partes.append(f"abatidas={len(resultado.abatidas)}")
    if resultado.comprovante_id:
        partes.append("comprovante")
    if resultado.cadastro:
        partes.append(f"cadastro={resultado.cadastro.campo}")
    return " ".join(partes)


def carregar_export(caminho: Path) -> tuple[list[LinhaDoExport], dict[str, bytes], Roteiro]:
    """Le um export do WhatsApp — o `.zip` do iOS ou uma pasta com `_chat.txt` + `cenario.json`.

    A pasta e o formato dos exports sinteticos: sem anexos e com o roteiro ao lado, versionavel em
    texto. O zip continua sendo o do grupo real, que traz as fotos junto.
    """
    if caminho.is_dir():
        chat = caminho / "_chat.txt"
        anexos = {p.name: p.read_bytes() for p in caminho.iterdir() if p.suffix.lower() != ".txt"}
        roteiro = Roteiro.de_json(caminho / "cenario.json")
        return ler_export(chat), {k: v for k, v in anexos.items() if k != "cenario.json"}, roteiro

    with zipfile.ZipFile(caminho) as zf:
        anexos = {nome: zf.read(nome) for nome in zf.namelist() if not nome.endswith(".txt")}
        chat_bruto = zf.read("_chat.txt").decode("utf-8")
    destino = Path(os.environ.get("REPLAY_TMP", "/tmp")) / "_chat_replay.txt"
    destino.write_text(chat_bruto, encoding="utf-8")
    return ler_export(destino), anexos, ROTEIRO_DA_YASMIN


async def rodar(*, com_ocr: bool, com_llm: bool, export: Path) -> int:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        print("TEST_DATABASE_URL obrigatorio (o replay escreve e faz rollback).", file=sys.stderr)
        return 2
    if not export.exists():
        print(f"export nao encontrado: {export}", file=sys.stderr)
        return 2

    linhas, anexos, roteiro = carregar_export(export)

    ler_comprovante = leitor_de_comprovante(get_settings()) if com_ocr else None
    if com_ocr and ler_comprovante is None:
        print("--ocr pedido, mas OPENROUTER_API_KEY nao esta no ambiente.", file=sys.stderr)
        return 2
    ler_intencao = leitor_de_intencao(get_settings()) if com_llm else None
    if com_llm and ler_intencao is None:
        print("--llm pedido, mas DEEPSEEK_API_KEY nao esta no ambiente.", file=sys.stderr)
        return 2

    conn = await psycopg.AsyncConnection.connect(
        url, autocommit=False, row_factory=dict_row, prepare_threshold=None
    )
    try:
        cenario = await montar_cenario(conn, roteiro)
        falas = Falas()
        ouvidos = " · ".join(
            ["ocr" if ler_comprovante else "sem ocr", "llm" if ler_intencao else "allowlist"]
        )
        print(
            f"# Replay do Grupo financeiro — {len(linhas)} mensagens ({export.name}) — {ouvidos}\n"
        )

        for linha in linhas:
            if linha.sistema:
                print(f"[{linha.indice:02d}] (sistema) {linha.texto[:60]}")
                continue
            if linha.apagada:
                # O export nao diz QUAL mensagem morreu — sem o id, a delecao nao tem alvo. Fica
                # visivel como buraco conhecido do replay (o teste de delecao cobre a porta).
                print(f"[{linha.indice:02d}] (mensagem apagada — sem alvo no export)")
                continue
            if linha.vazia:
                print(f"[{linha.indice:02d}] (linha sem corpo no export — {linha.autor})")
                continue

            resultado = await processar_mensagem_do_grupo(
                conn,
                _mensagem(linha, cenario, anexos),
                enviar=falas,
                ler_comprovante=ler_comprovante,
                ler_intencao=ler_intencao,
            )
            corpo = linha.texto.replace("\n", " / ") or f"<{linha.tipo}: {linha.anexo}>"
            print(f"[{linha.indice:02d}] {linha.autor}: {corpo[:88]}")
            print(f"      → {_resumo(resultado)}")
            for dita in falas.drenar():
                for pedaco in dita.split("\n"):
                    print(f"      🤖 {pedaco}")

        await _relatorio_final(conn, cenario, ultima=linhas[-1].quando)
        return 0
    finally:
        await conn.rollback()
        await conn.close()


async def _relatorio_final(
    conn: psycopg.AsyncConnection[dict[str, Any]], cenario: Cenario, *, ultima: datetime
) -> None:
    print("\n# Estado final\n")
    cur = await conn.execute(
        """
        SELECT m.nome AS modelo, v.valor, v.data, v.cliente_nome, v.forma_pagamento,
               v.comprovante_id IS NOT NULL AS comprovada
          FROM barravips.vendas_registradas v
          JOIN barravips.modelos m ON m.id = v.modelo_id
         WHERE v.anulada_em IS NULL
         ORDER BY v.data, v.created_at
        """
    )
    vendas = list(await cur.fetchall())
    print(f"## Vendas registradas: {len(vendas)}")
    for v in vendas:
        forma = v["forma_pagamento"] or "—"
        marca = "✓" if v["comprovada"] else " "
        print(
            f"  {marca} {v['data']} · {v['modelo'].split()[0]:8} · {formatar_reais(v['valor']):>12}"
            f" · {forma:8} · {v['cliente_nome'] or '—'}"
        )

    cur = await conn.execute(
        """
        SELECT descricao, valor, quitada_em IS NOT NULL AS paga
          FROM barravips.cobrancas_da_agencia WHERE anulada_em IS NULL ORDER BY data
        """
    )
    cobrancas = list(await cur.fetchall())
    print(f"\n## Cobrancas da agencia: {len(cobrancas)}")
    for c in cobrancas:
        print(
            f"  {'paga' if c['paga'] else 'ABERTA'} · {formatar_reais(c['valor']):>12} · {c['descricao']}"
        )

    cur = await conn.execute(
        """
        SELECT classificacao, valor, valor_abatido, chave_conhecida
          FROM barravips.comprovantes_do_grupo ORDER BY created_at
        """
    )
    comprovantes = list(await cur.fetchall())
    print(f"\n## Comprovantes lidos: {len(comprovantes)}")
    for c in comprovantes:
        valor = formatar_reais(c["valor"]) if c["valor"] is not None else "—"
        print(
            f"  {c['classificacao']:16} · {valor:>12} · abatido {formatar_reais(c['valor_abatido'])}"
            f" · chave {'conhecida' if c['chave_conhecida'] else 'FORA DA LISTA'}"
        )

    print("\n## Fechamento por modelo")
    for nome, modelo_id in cenario.modelos.items():
        extrato = await fechamento_da_modelo(conn, modelo_id)
        if extrato.vendas == 0 and not extrato.cobrancas:
            continue
        print(
            f"  {nome:8} vendido {formatar_reais(extrato.vendido):>12} · "
            f"comprovado {formatar_reais(extrato.comprovado):>12} · "
            f"especie {formatar_reais(extrato.em_especie):>12} · "
            f"falta comprovar {formatar_reais(extrato.a_comprovar):>12} · "
            f"sem forma {formatar_reais(extrato.sem_forma):>12} · "
            f"debito {formatar_reais(extrato.debito):>10}"
        )
        for divergencia in extrato.divergencias:
            print(f"           ⚠️ {divergencia.tipo} {formatar_reais(divergencia.valor)}")

    print("\n## Razao (saldo com sinal, ticket 02)")
    for nome, modelo_id in cenario.modelos.items():
        print(linha_do_saldo(nome, await razao_da_modelo(conn, modelo_id)))

    grupo = await buscar_grupo_por_jid(conn, cenario.grupo_jid)
    assert grupo is not None
    # 08:00 BRT do dia seguinte a ultima mensagem — a rotina e relativa ao export, e nao a uma
    # data fixa: com data cravada, um export sintetico de outra semana mediria "silencio" so
    # porque a manha simulada caiu antes das vendas.
    manha = (ultima + BRT).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
    manha = manha - BRT
    rotina = await cobrar_pendencias_do_grupo(conn, grupo, agora=manha)
    print(f"\n## Rotina da manha seguinte ({(manha + BRT):%d/%m} 08:00 BRT)")
    print(f"  status={rotina.status}")
    for pedaco in (rotina.fala or "(silencio)").split("\n"):
        print(f"  🤖 {pedaco}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr", action="store_true", help="le as imagens de verdade (custa)")
    parser.add_argument(
        "--llm", action="store_true", help="liga o leitor de intencao da producao (custa)"
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=ZIP_DO_EXPORT,
        help="zip do WhatsApp ou pasta com _chat.txt + cenario.json",
    )
    args = parser.parse_args()
    return asyncio.run(rodar(com_ocr=args.ocr, com_llm=args.llm, export=args.export))


if __name__ == "__main__":
    raise SystemExit(main())
