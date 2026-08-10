"""Renderiza o system prompt v1 com um perfil de modelo SINTÉTICO fixo, para a sessão
de pontuação offline (ponto 4). Usa as MESMAS funções de render de produção (persona.py)
para que o candidato seja byte-fiel ao prefixo real (BP_GERAL + BP_MODELO).
Imprime o prompt em stdout."""
import sys
from datetime import datetime, timedelta
from barra.agente.persona import (
    render_prefixo_geral,
    render_bp3,
    render_contexto_dinamico,
    IdentidadeModelo,
)

# ---- Perfil de modelo SINTÉTICO FIXO (eb04 não está no painel; prod só tem "Lucia Teste") ----
# Valores/programas/endereço placeholder coerentes. NÃO afeta a métrica:
# urgência/pergunta colada ao preço independe dos valores.
IDENT = IdentidadeModelo(
    nome="Manu",
    idade=25,
    idiomas=["pt-BR"],
    localizacao_operacional="Barra (Campinas-SP)",
    tipos_aceitos=["interno", "externo"],
)
PROGRAMAS = [
    {"nome": "Encontro", "duracao_nome": "1 hora", "preco": 400},
    {"nome": "Encontro", "duracao_nome": "2 horas", "preco": 700},
    {"nome": "Pernoite", "duracao_nome": "12 horas", "preco": 2500},
    {"nome": "Atendimento ao casal", "duracao_nome": "1 hora", "preco": 700},
]
FETICHES = [
    {"nome": "Beijo na boca", "preco": None},
    {"nome": "Oral sem camisinha", "preco": None},
    {"nome": "Namoradinha", "preco": None},
]

# desconto_max_pct default de settings; passo explícito 0.10 para não depender de .env
PREFIXO = render_prefixo_geral(desconto_max_pct=0.10)
BP3 = render_bp3(IDENT, PROGRAMAS, FETICHES)

# contexto dinâmico fixo coerente (agenda livre; estado Qualificado) — o candidato cota normalmente
agora = datetime(2026, 6, 13, 20, 0)
CTX = render_contexto_dinamico(
    numero_curto=1,
    estado="Qualificado",
    tipo_atendimento=None,
    urgencia=None,
    pix_status="nao_aplicavel",
    data_desejada=None,
    horario_desejado=None,
    endereco=None,
    bairro=None,
    cliente_nome=None,
    recorrente=False,
    historico_anteriores=None,
    ultimo_motivo_perda=None,
    observacoes_internas=None,
    data_atual=agora.strftime("%a %d/%m"),
    hora_atual=agora.strftime("%H:%M"),
    bloqueios=[],
    disponibilidade=[],
)

print("===PREFIXO_GERAL===")
print(PREFIXO)
print("===BP_MODELO===")
print(BP3)
print("===CONTEXTO_DINAMICO===")
print(CTX)
