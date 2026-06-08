"""F0.10 — Invariante "nunca trava por Pix" vira gate CONFIÁVEL no CI.

CONTEXT.md ("Pix de deslocamento"): o comprovante **sempre** faz o atendimento avançar — nunca
trava por Pix. Checagens OK validam em silêncio (`pix_status='validado'`); divergência/suspeita
marca o comprovante como duvidoso (`pix_status='em_revisao'`) mas o fluxo **avança igual**. O
relatório de prontidão registra os **4 ramos** (validado, a menor, chave divergente,
plausibilidade falsa): todos avançam para `Confirmado`.

A cobertura viva desses 4 ramos é `tests/integracao/test_validar_pix.py` — `needs_db`, contra o
Postgres real. O problema apontado pelo relatório: *"Único gate é needs-DB — pulado sem
TEST_DATABASE_URL."* Um `needs_db` é **silenciosamente pulado** quando falta a env var; e nada
impedia que um dos 4 ramos fosse deletado, renomeado ou tivesse a asserção de "avança" enfraquecida
sem deixar a suíte vermelha (um teste a menos não falha nada). Com o Postgres efêmero da CI (F0.1)
os ramos passam a **rodar** a cada PR; falta a rede que garante que eles **continuam existindo e
provando o invariante**.

Este teste é essa rede: extrai por AST o `test_validar_pix.py` e reprova o PR se qualquer um dos
4 ramos sumir, perder o marcador `needs_db` (deixaria de rodar no Postgres efêmero — viraria um
no-op pulável) ou parar de asseverar que o atendimento avança para `Confirmado`. É **determinístico
e sem banco** — roda no `make test` padrão, NÃO é `needs_db`, então nunca fica pulado: gate de PR
de verdade, espelhando F0.1 (wiring da CI) e F0.2 (montador nunca carrega painel-only).

Extrai por AST (não grep no texto-fonte) de propósito: os docstrings/comentários do arquivo citam
"Confirmado"/"em_revisao"/"nunca trava" legitimamente em prosa; só os literais dentro de `assert`
e dos decorators são prova de comportamento testado.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TESTE_PIX = Path(__file__).resolve().parent / "integracao" / "test_validar_pix.py"

# Os 4 ramos do invariante "nunca trava por Pix" (relatório de prontidão), por nome de função de
# teste em `test_validar_pix.py`. Cada um deve: (1) existir, (2) ser `needs_db` — senão deixa de
# rodar no Postgres efêmero da CI (F0.1) e vira um gate pulável —, (3) asseverar que o atendimento
# avança para `Confirmado` (o invariante nunca-trava) com o `pix_status` esperado do ramo.
RAMOS: dict[str, str] = {
    "test_validado_avanca_confirmado_e_enfileira_card": "validado",
    "test_underpay_em_revisao_mas_fluxo_avanca": "em_revisao",
    "test_chave_divergente_em_revisao": "em_revisao",
    "test_plausibilidade_falsa_em_revisao": "em_revisao",
}

# Estado terminal do invariante: o atendimento SEMPRE avança, nunca fica preso em
# Aguardando_confirmacao. Tem de aparecer numa asserção de TODO ramo.
ESTADO_AVANCA = "Confirmado"


def _func_defs(arvore: ast.Module) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    return {
        no.name: no for no in arvore.body if isinstance(no, ast.AsyncFunctionDef | ast.FunctionDef)
    }


def _eh_needs_db(func: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    """True se a função tem o decorator `@pytest.mark.needs_db`."""
    for dec in func.decorator_list:
        for sub in ast.walk(dec):
            if isinstance(sub, ast.Attribute) and sub.attr == "needs_db":
                return True
    return False


def _constantes_str_em_asserts(func: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    """Todos os literais de string que aparecem dentro de `assert ...` da função.

    Só `assert` conta — comparações soltas, comentários e docstrings ficam de fora, então o match é
    sobre comportamento de fato asseverado, não sobre prosa que cita "Confirmado"."""
    achados: set[str] = set()
    for no in ast.walk(func):
        if isinstance(no, ast.Assert):
            for sub in ast.walk(no):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    achados.add(sub.value)
    return achados


def test_arquivo_dos_ramos_existe() -> None:
    """Âncora anti-vácuo: sem o arquivo de cobertura, nada abaixo provaria nada."""
    assert _TESTE_PIX.is_file(), (
        f"falta {_TESTE_PIX.name}: é a cobertura viva dos 4 ramos do 'nunca trava por Pix'"
    )


def test_os_quatro_ramos_existem_sao_needs_db_e_avancam() -> None:
    """Os 4 ramos existem, são `needs_db` (rodam no Postgres efêmero da CI) e asseveram avanço."""
    arvore = ast.parse(_TESTE_PIX.read_text("utf-8"))
    funcs = _func_defs(arvore)

    for nome, pix_status in RAMOS.items():
        func = funcs.get(nome)
        assert func is not None, (
            f"ramo do 'nunca trava por Pix' sumiu: {nome}() não existe mais em "
            f"{_TESTE_PIX.name} — o gate exige os 4 ramos (validado, a menor, chave divergente, "
            f"plausibilidade falsa)"
        )
        assert _eh_needs_db(func), (
            f"{nome}() perdeu @pytest.mark.needs_db — deixaria de rodar no Postgres efêmero da CI "
            f"(F0.1) e o gate viraria pulável; o invariante 'nunca trava por Pix' só se prova "
            f"contra o banco real"
        )
        asserts = _constantes_str_em_asserts(func)
        assert ESTADO_AVANCA in asserts, (
            f"{nome}() não assevera mais que o atendimento avança para {ESTADO_AVANCA!r}: o "
            f"invariante 'nunca trava por Pix' diz que o fluxo SEMPRE avança, mesmo duvidoso"
        )
        assert pix_status in asserts, (
            f"{nome}() não assevera mais pix_status={pix_status!r}: o ramo precisa provar que "
            f"validado valida em silêncio e divergência vira em_revisao informativo (sem travar)"
        )


def test_pelo_menos_quatro_ramos_needs_db() -> None:
    """Âncora anti-vácuo: o arquivo tem >= 4 testes `needs_db` (a parse não veio vazia)."""
    arvore = ast.parse(_TESTE_PIX.read_text("utf-8"))
    needs_db = [nome for nome, f in _func_defs(arvore).items() if _eh_needs_db(f)]
    assert len(needs_db) >= len(RAMOS), (
        f"esperava >= {len(RAMOS)} testes needs_db em {_TESTE_PIX.name}, achei {len(needs_db)}: "
        f"{needs_db}"
    )
