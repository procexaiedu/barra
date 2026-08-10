"""Harness FIEL ao WhatsApp que conduz o agente real contra um cliente-LLM (DeepSeek) ate um
DESFECHO TERMINAL natural (`Fechado` / `Perdido`).

Estende o `replay_agente_fiel.py` (que parava no handoff, `Aguardando_confirmacao`/IA pausada):
reusa o cliente-LLM ancorado na persona real do corpus + a conducao turno-a-turno (debounce,
persistencia por bolha, ordem uuidv7, trace), e adiciona a CAUDA DETERMINISTICA que o cliente de
texto sozinho nao alcanca, sempre por porta de dominio REAL:

  - MIDIA NATURAL do cliente (o cliente real manda isso):
      interno         -> Foto de portaria  (`atendimentos.service.handoff_foto_portaria_ia`)
      externo c/ Pix  -> comprovante Pix    (INSERT comprovantes_pix + `aplicar_comando('atualizar_pix')`)
      pickup / remoto -> sem midia (a IA ja pausou no slot reservado)
  - FECHAMENTO DA MODELO (no P0 a modelo e humano digitando um comando regex no grupo de
    Coordenacao, sem IA): `escaladas.service.aplicar_comando('registrar_fechado'/'registrar_perdido')`
    com origem='grupo_coordenacao', autor='modelo'.

DESFECHO NATURAL: nao força o resultado do corpus. Se o cliente-LLM engajou e a IA reservou o slot
-> Fechado pelo `valor_acordado` que a IA negociou NESTA run; se esfriou/recusou/sumiu antes de
cravar horario -> Perdido com motivo coerente.

§0: gasta credito DeepSeek (agente + cliente-sim, AUTORIZADO). Seed+ROLLBACK contra prod — nada
commita; nao toca WhatsApp/Redis/prod.

Uso (de api/):
  PYTHONPATH=. TEST_DATABASE_URL="$DATABASE_URL" uv run python \
      ../scripts/eval_corpus/replay_agente_terminal.py --out /caminho/terminal.json
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from evals.e2e.extracao import extrair_perfil_por_ref
from evals.e2e.perfil import perfil_para_fixture
from evals.harness import estado_pos_turno, habilitar_tracing, seedar
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.core.llm import criar_chat_deepseek
from barra.dominio.atendimentos.service import handoff_foto_portaria_ia
from barra.dominio.escaladas.service import aplicar_comando
from barra.settings import Settings, get_settings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Reusa a maquinaria fiel (mesmo cliente-LLM e mesma conducao turno-a-turno da prod).
from replay_agente_fiel import (  # noqa: E402
    _ancora_agora_utc,
    _bolhas,
    _inserir_bolha,
    _rodar_turno_fiel,
)
from dados_reais import carregar  # noqa: E402
from sim_deepseek import FalaCliente, prompt_cliente, sanear_fala_cliente  # noqa: E402

# As 8 conversas-chave do conversas_chave_vendedor.html, na ordem de exibicao, com o tipo do
# cenario. O tipo so serve para (a) dar a modelo sintetica o `tipo_atendimento_aceito` certo e
# (b) escolher o beat de midia; o desfecho em si e o que a run produzir. Aponta para threads
# REAIS (@lid do cliente) -> PII, fora do git (ver dados_reais.py).
CENARIOS: list[dict[str, str]] = carregar("replay_agente_terminal", "CENARIOS")

MAX_TURNOS = 24  # trava de custo/tempo; o cliente-sim costuma cravar/encerrar antes
ESTADOS_COMPROMETIDO = {"Aguardando_confirmacao", "Confirmado", "Em_execucao"}
# Programas da modelo sintetica: cobre interno/externo (Encontro/Pernoite) + remoto (Video chamada),
# para o agente conseguir cotar qualquer um dos 8 cenarios sem recusar por catalogo.
PROGRAMAS = [
    {"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 400, "ordem": 1},
    {"nome": "Encontro", "duracao_nome": "2 horas", "horas": 2, "preco": 700, "ordem": 2},
    {"nome": "Pernoite", "duracao_nome": "12 horas", "horas": 12, "preco": 2500, "ordem": 9},
    {"nome": "Video chamada", "duracao_nome": "15 minutos", "horas": 0.25, "preco": 150, "ordem": 1},
]
# Ficha REAL de cada modelo, extraida das mensagens do PROPRIO vendedor no corpus (nome, preco,
# endereco, chave pix) — torna a comparacao lado a lado fiel: o agente cota o MESMO numero, no MESMO
# endereco que o vendedor. `preco` = tabela que o vendedor anunciou (o agente negocia sozinho, como
# ele fez). Extras sem programa proprio (anal, cartao) nao sao modelados. Refs sem nome claro do
# vendedor ficam com o nome sintetico. So aplica aos 8 cenarios; o resto cai no PROGRAMAS generico.
# Nome + endereco + chave Pix de pessoas reais -> PII, fora do git (ver dados_reais.py).
MODELOS_REAIS: dict[str, dict[str, Any]] = carregar("replay_agente_terminal", "MODELOS_REAIS")
_RE_PRECO = re.compile(r"R?\$?\s*([1-9]\d{2,4})(?:[.,]00)?\b")
# "Rua Latino Coelho, 421" / "Av. Aquidabã 130": logradouro + numero, para excluir da varredura
# de preco no fallback do fechamento.
_RE_TRECHO_ENDERECO = re.compile(
    r"\b(?:rua|av\.?|avenida|alameda|travessa)\s+[^\n,]{2,40},?\s*\d+", re.IGNORECASE
)
_OBJ_PRECO = ("caro", "puxado", "desconto", "menos", "baixa", "200", "250", "300", "consegue por",
              "so tenho", "só tenho", "ficou acima", "acima", "fora do meu")
_OBJ_RISCO = ("golpe", "confio", "confiar", "segur", "medo", "fake", "falsa", "falso", "calote",
              "tomar um", "real mesmo", "é real", "e real", "vc é de verdade", "vc e de verdade")


def _fixture_cenario(perfil: Any, tipo: str) -> dict[str, Any]:
    """Fixture do harness com a modelo sintetica ajustada ao cenario (deep-copy: nao muta o dict
    global MODELO_SINTETICA compartilhado)."""
    fix = copy.deepcopy(perfil_para_fixture(perfil))
    modelo = fix["cenario"]["modelo"]
    modelo["tipo_atendimento_aceito"] = ["interno", "externo", "remoto"]
    real = MODELOS_REAIS.get(perfil.thread_ref or "")
    if real:  # ficha real do vendedor (nome/endereco/programas/pix) — comparacao fiel
        modelo.update(copy.deepcopy(real))
    else:
        modelo["programas"] = copy.deepcopy(PROGRAMAS)
    modelo.setdefault("chave_pix", "manu@pix.com")
    return fix


async def _ler_atendimento(conn: AsyncConnection[dict[str, Any]], aid: UUID) -> dict[str, Any]:
    res = await conn.execute(
        "SELECT estado, pix_status::text AS pix_status, "
        "       tipo_atendimento::text AS tipo_atendimento, valor_acordado "
        "FROM barravips.atendimentos WHERE id = %s",
        (aid,),
    )
    return dict(await res.fetchone() or {})


def _valor_fechamento(valor_acordado: Any, textos_ia: list[str], minimo: int = 300) -> Decimal:
    """Valor que a modelo registra no fechamento = o que a IA negociou nesta run. Preferimos o
    campo estruturado `valor_acordado`; senao, o ultimo numero de preco que a IA citou; senao 400."""
    if valor_acordado is not None:
        try:
            return Decimal(str(valor_acordado))
        except (InvalidOperation, ValueError):
            pass
    candidatos: list[str] = []
    for txt in reversed(textos_ia):
        # numero de endereco ("Rua X, 421") nao e preco: apaga o trecho de endereco antes de
        # varrer (bug real: fechamento gravado como 421 = numero da rua da fixture).
        txt_sem_endereco = _RE_TRECHO_ENDERECO.sub(" ", txt or "")
        candidatos.extend(reversed(_RE_PRECO.findall(txt_sem_endereco)))
    # preco de encontro presencial nunca fica abaixo do piso (~340 na fixture): numeros menores
    # sao Pix (100) ou video chamada (150) citados de passagem (bug real: fechamento gravado 150).
    for achado in candidatos:
        try:
            v = Decimal(achado)
        except (InvalidOperation, ValueError):
            continue
        if v >= minimo:
            return v
    return Decimal("400")


def _motivo_perda(textos_cliente: list[str], estado: str) -> tuple[str, str | None]:
    """Motivo coerente do Perdido natural: risco (medo de golpe), preco (objecao/pechincha) ou
    sumiu (silenciou/nao cravou)."""
    blob = " ".join(textos_cliente).lower()
    if any(p in blob for p in _OBJ_RISCO):
        return "risco", None
    if any(p in blob for p in _OBJ_PRECO):
        return "preco", None
    return "sumiu", None


async def _midia_cliente(
    conn: AsyncConnection[dict[str, Any]],
    cen: Any,
    contador: list[int],
    rotulo: str,
) -> UUID:
    """Insere UMA bolha de imagem (direcao=cliente) — o cliente real mandaria o Pix/foto aqui —
    e devolve o mensagem_id (FK que o handoff de portaria / comprovante de Pix exigem)."""
    contador[0] += 1
    mid = uuid4()
    await conn.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key,
             evolution_message_id, created_at)
        VALUES (%s, %s, %s, 'cliente'::barravips.direcao_mensagem_enum, 'imagem', %s, %s, %s,
                now() - make_interval(secs => %s))
        """,
        (mid, cen.conversa_id, cen.atendimento_id, f"[{rotulo}]",
         f"terminal/{rotulo}/{mid.hex}.jpg", f"term-{uuid4().hex}", 1000 - contador[0]),
    )
    return mid


async def _cravar_terminal(
    conn: AsyncConnection[dict[str, Any]],
    cen: Any,
    contador: list[int],
    comprometido: bool,
    textos_ia: list[str],
    textos_cliente: list[str],
) -> dict[str, Any]:
    """Caminho deterministico ate o terminal natural. Devolve os eventos de cauda + desfecho."""
    eventos: list[dict[str, Any]] = []
    at = await _ler_atendimento(conn, cen.atendimento_id)
    estado = at.get("estado") or "Novo"

    if not comprometido:
        motivo, obs = _motivo_perda(textos_cliente, estado)
        await aplicar_comando(
            conn, origem="grupo_coordenacao", autor="modelo",
            atendimento_id=cen.atendimento_id, comando="registrar_perdido",
            payload={"motivo": motivo, "observacao": obs},
        )
        eventos.append({
            "lado": "MODELO", "tipo": "comando",
            "texto": f"perdido {motivo}", "resultado": "Perdido",
        })
        return {"eventos": eventos, "desfecho": "Perdido", "motivo_perda": motivo,
                "valor_final": None, "estado_antes_terminal": estado}

    # --- comprometido: cliente manda a midia natural, depois a modelo fecha ---
    tipo = (at.get("tipo_atendimento") or "").lower()
    pix_status = (at.get("pix_status") or "").lower()
    midia_rotulo: str | None = None

    if tipo == "interno":
        mid = await _midia_cliente(conn, cen, contador, "foto de portaria")
        await handoff_foto_portaria_ia(
            conn, atendimento_id=cen.atendimento_id, mensagem_id=mid, media_object_key=None
        )
        midia_rotulo = "foto de portaria"
    elif pix_status == "aguardando":  # externo com Pix de deslocamento (nao pickup)
        mid = await _midia_cliente(conn, cen, contador, "comprovante pix")
        await conn.execute(
            """
            INSERT INTO barravips.comprovantes_pix
              (atendimento_id, mensagem_id, valor_extraido, chave_extraida, titular_extraido,
               timestamp_extraido, decisao_pipeline, motivo_em_revisao)
            VALUES (%s, %s, NULL, NULL, NULL, NULL, 'em_revisao', 'sem_ocr')
            """,
            (cen.atendimento_id, mid),
        )
        await aplicar_comando(
            conn, origem="pipeline_pix", autor="sistema",
            atendimento_id=cen.atendimento_id, comando="atualizar_pix",
            payload={"decisao": "em_revisao", "motivo": "sem_ocr"},
        )
        midia_rotulo = "comprovante pix"
    # pickup / remoto: sem midia — a IA ja reservou o slot (Aguardando_confirmacao)

    if midia_rotulo:
        eventos.append({"lado": "C", "tipo": "midia", "rotulo": midia_rotulo})

    valor = _valor_fechamento(
        at.get("valor_acordado"), textos_ia, minimo=0 if tipo == "remoto" else 300
    )
    await aplicar_comando(
        conn, origem="grupo_coordenacao", autor="modelo",
        atendimento_id=cen.atendimento_id, comando="registrar_fechado",
        payload={"valor_final": valor},
    )
    eventos.append({
        "lado": "MODELO", "tipo": "comando",
        "texto": f"fechado {valor}", "resultado": "Fechado",
    })
    estado_final = (await _ler_atendimento(conn, cen.atendimento_id)).get("estado")
    return {"eventos": eventos, "desfecho": "Fechado", "motivo_perda": None,
            "valor_final": str(valor), "estado_antes_terminal": estado,
            "estado_final_db": estado_final}


async def _replay_um(dsn: str, cen_spec: dict[str, str], graph: Any, s: Settings) -> dict[str, Any]:
    ref, tipo = cen_spec["ref"], cen_spec["tipo"]
    conn = await AsyncConnection.connect(dsn, row_factory=dict_row, autocommit=False)
    try:
        perfil = await extrair_perfil_por_ref(conn, ref)
        if perfil is None:
            return {"ref": ref, "erro": "ref sem falas em corpus.turnos"}

        cen = await seedar(conn, _fixture_cenario(perfil, tipo))
        cli = criar_chat_deepseek(s).with_structured_output(FalaCliente, method="function_calling")

        contador = [0]
        hist: list[dict[str, str]] = []
        eventos: list[dict[str, Any]] = []
        textos_ia: list[str] = []
        textos_cliente: list[str] = []
        custo = 0.0
        encerrou_cliente = False
        ultimo_est: dict[str, Any] = {}

        bolhas_c = _bolhas(perfil.abertura)  # turno 0 = abertura REAL do corpus
        ultimo_cli = "\n".join(bolhas_c)
        hist.append({"lado": "C", "bolhas": ultimo_cli})
        ancora = _ancora_agora_utc()  # clock injection: âncora fixa coerente (manhã) por run

        for _ in range(MAX_TURNOS):
            for b in bolhas_c:
                eventos.append({"lado": "C", "tipo": "texto", "texto": b})
            textos_cliente.extend(bolhas_c)

            texto, tools_turno, est, c = await _rodar_turno_fiel(
                conn, cen, bolhas_c, graph, contador, agora_utc=ancora
            )
            custo += c
            ultimo_est = est
            # Fidelidade WhatsApp: a IA mandou midia (enviar_midia) -> o cliente VE a foto/video
            # chegar. Sem o marcador o cliente-sim fica cego e re-pede a midia em loop (perda que
            # e artefato do harness, nao conduta — confirmado no Langfuse, rodada novas32 r1).
            n_midias = sum(1 for t in tools_turno if t == "enviar_midia")
            if n_midias:
                eventos.append({"lado": "IA", "tipo": "midia", "texto": f"[enviou {n_midias} midia(s)]"})
            if texto.strip():
                eventos.append({"lado": "IA", "tipo": "texto", "texto": texto})
                textos_ia.append(texto)
            bolhas_m = "\n\n".join(
                p for p in (texto.strip(), "[te mandou fotos suas]" if n_midias else "") if p
            )
            hist.append({"lado": "M", "bolhas": bolhas_m})

            # Quebra a conducao quando a IA crava o slot (venda) OU pausa por handoff/escalada.
            # O COMPROMISSO em si e julgado so pelo ESTADO (abaixo): `ia_pausada` sozinho tambem
            # dispara em escalada (ex.: lowball -> fora_de_oferta) ainda em Triagem, que NAO e venda.
            if est.get("estado") in ESTADOS_COMPROMETIDO or est.get("ia_pausada"):
                break

            # Ate 2 retentativas se a fala vier invalida (so voz de modelo vazada, ou repete a
            # bolha anterior ao pe da letra — coisa que humano real nao faz): melhor tentar de
            # novo do que encerrar o cenario cedo por um artefato do ClienteLLM.
            fala = None
            bolhas_c = []
            for _tentativa in range(3):
                try:
                    fala = await cli.ainvoke(prompt_cliente(perfil.persona, hist))
                except Exception:
                    fala = None
                    break
                if fala.encerrou or not fala.bolhas.strip():
                    break
                candidatas = sanear_fala_cliente(_bolhas(fala.bolhas), perfil.linhas_vendedor)
                if candidatas and "\n".join(candidatas) != ultimo_cli:
                    bolhas_c = candidatas
                    break
            if fala is None or fala.encerrou or not fala.bolhas.strip() or not bolhas_c:
                encerrou_cliente = True
                break
            ultimo_cli = "\n".join(bolhas_c)
            hist.append({"lado": "C", "bolhas": ultimo_cli})

        # Comprometido = a IA cravou o slot (estado real de venda). Pausa por escalada em Triagem/
        # Qualificado NAO conta: vira Perdido com motivo coerente.
        comprometido = ultimo_est.get("estado") in ESTADOS_COMPROMETIDO

        terminal = await _cravar_terminal(
            conn, cen, contador, comprometido, textos_ia, textos_cliente
        )
        eventos.extend(terminal["eventos"])

        return {
            "ref": ref,
            "tipo_cenario": tipo,
            "perfil_nome": perfil.nome,
            "desfecho_real": perfil.desfecho_real,
            "comprometido": comprometido,
            "encerrou_cliente": encerrou_cliente,
            "desfecho_sim": terminal["desfecho"],
            "valor_final": terminal["valor_final"],
            "motivo_perda": terminal["motivo_perda"],
            "estado_antes_terminal": terminal["estado_antes_terminal"],
            "custo_brl": round(custo, 6),
            "n_eventos": len(eventos),
            "eventos": eventos,
        }
    except Exception as exc:
        import traceback
        return {"ref": ref, "erro": f"{type(exc).__name__}: {exc}",
                "tb": traceback.format_exc()[-1200:]}
    finally:
        await conn.rollback()
        await conn.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--conc", type=int, default=4)
    ap.add_argument("--refs", help="CSV de refs (subconjunto; default: todas)")
    args = ap.parse_args()

    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("defina TEST_DATABASE_URL (ou DATABASE_URL)")

    from barra.agente.graph import build_graph

    ligou = habilitar_tracing()
    print(f"langfuse: {'ligado' if ligou else 'desligado'}", file=sys.stderr)
    s = get_settings()
    graph = build_graph()
    sem = asyncio.Semaphore(args.conc)

    refs_filtro = {r.strip() for r in args.refs.split(",")} if args.refs else None
    specs = [c for c in CENARIOS if refs_filtro is None or c["ref"] in refs_filtro]

    async def _tarefa(cen_spec: dict[str, str]) -> dict[str, Any]:
        async with sem:
            ref = cen_spec["ref"]
            print(f"[start] {ref}", file=sys.stderr)
            res = await _replay_um(dsn, cen_spec, graph, s)
            tag = res.get("erro") or (
                f"{res.get('desfecho_sim')} "
                f"{res.get('valor_final') or res.get('motivo_perda')} "
                f"R${res.get('custo_brl')}"
            )
            print(f"[done ] {ref} — {tag}", file=sys.stderr)
            return res

    resultados = await asyncio.gather(*(_tarefa(c) for c in specs))
    total = sum(r.get("custo_brl", 0.0) for r in resultados)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"resultados": resultados, "custo_total_brl": round(total, 6)},
                  fh, ensure_ascii=False, indent=2)
    print(f"\nOK — {len(resultados)} cenarios, custo R${total:.4f} -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
