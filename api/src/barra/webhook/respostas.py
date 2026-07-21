"""Texto das respostas da IA aos comandos no grupo de Coordenação (UX §6).

Duas superfícies, ambas voz operacional interna (curta, factual, sem persona):
- **Confirmação** (§6.1): todo comando válido recebe um eco curto — "nunca sucesso silencioso".
- **Erro com recuperação** (§6.2): todo comando malformado/rejeitado diz a causa + como consertar,
  com exemplo — "nunca erro sem caminho de saída".

Funções puras (sem I/O): o webhook (`routes._processar_grupo`) decide quando enviar e por qual
canal/`tipo` (`confirmacao`/`erro_comando`); aqui só se monta o texto. A interpretação do comando
é determinística (regex no `parser`); NLP livre é IA Admin (P1).
"""

from typing import Any

from barra.core.moeda import formatar_brl

# --- Confirmações (§6.1) -----------------------------------------------------------------------


def texto_confirmacao(comando: str, payload: dict[str, Any], numero_curto: int) -> str:
    """Eco curto de um comando aplicado com sucesso (§6.1). Uma linha, com o `#N`, sem rodapé.

    O repasse (`· repasse R$ X` quando há snapshot, §9.3) fica de fora no P0: calculá-lo aqui
    duplicaria a lógica do módulo Financeiro (líquido de taxa de cartão). Some sem alarde, igual
    ao `Registro de resultado` que fecha com repasse pendente.
    """
    if comando == "registrar_fechado":
        return f"✅ #{numero_curto} fechado · {formatar_brl(payload['valor_final'])} registrado"
    if comando == "registrar_perdido":
        return f"✅ #{numero_curto} marcado como perdido · motivo: {payload['motivo']}"
    if comando == "devolver_para_ia":
        return f"✅ #{numero_curto} devolvido para a IA"
    if comando == "pausar_ia":
        return f"✅ #{numero_curto} IA pausada"
    return f"✅ #{numero_curto} registrado"  # defesa: comando sem eco próprio


# --- Erros com recuperação (§6.2) --------------------------------------------------------------

_ERRO_GENERICO = (
    "❓ Não consegui registrar. Fechar: *fechado 1500* · "
    "Perder: *perdido sumiu* · Devolver à IA: *IA assume* · Pausar a IA: *IA pausa*"
)

# Código do erro -> texto de recuperação (causa + como consertar + exemplo). Os 4 primeiros saem
# do parser (`comando.payload['motivo']` / `#N` ausente); os demais, do serviço (ErroDominio).
_ERROS: dict[str, str] = {
    "numero_curto_ausente": (
        "❓ Não sei qual atendimento. Responda direto no card — ou inclua o número: "
        "*fechado #42 1500*"
    ),
    "valor_ambiguo": "❓ Vi mais de um número aqui. Me manda só o valor final, ex.: *1500*",
    "valor_final_obrigatorio": "❓ Faltou o valor. Responda com o valor cobrado, ex.: *1500*",
    "motivo_perda_obrigatorio": (
        "❓ Por que foi perdido? Responda *perdido* + motivo: "
        "preço, sumiu, risco, indisponibilidade, fora_de_area ou outro"
    ),
    "observacao_obrigatoria": (
        "❓ Pro motivo 'outro', conta em uma linha o que rolou, ex.: "
        "*perdido outro cliente sumiu antes de fechar*"
    ),
    "conflito_estado": (
        "❓ Não deu pra mexer nesse atendimento agora — ele já foi finalizado ou a IA já está "
        "ativa. Confira no painel."
    ),
    "atendimento_nao_encontrado": "❓ Não achei esse atendimento aberto. Confira o número do card.",
}

# ErroDominio.code -> chave de `_ERROS`. Os obrigatórios de valor/motivo o parser já pega antes do
# serviço; ficam aqui para os caminhos que só o serviço alcança (ex.: motivo `outro` sem observação).
_DOMINIO_PARA_ERRO: dict[str, str] = {
    "VALOR_FINAL_OBRIGATORIO": "valor_final_obrigatorio",
    "MOTIVO_OBRIGATORIO": "motivo_perda_obrigatorio",
    "OBSERVACAO_OBRIGATORIA": "observacao_obrigatoria",
    "CONFLITO_ESTADO": "conflito_estado",
    "RECURSO_NAO_ENCONTRADO": "atendimento_nao_encontrado",
}


def texto_erro_comando(codigo: str | None) -> str:
    """Texto de recuperação de um erro de parsing/roteamento (§6.2). Código desconhecido cai no
    genérico, que lista os comandos válidos — nunca um beco sem saída."""
    return _ERROS.get(codigo or "", _ERRO_GENERICO)


def texto_erro_dominio(codigo: str) -> str:
    """Texto de recuperação para um `ErroDominio` levantado por `aplicar_comando` (§6.2)."""
    return texto_erro_comando(_DOMINIO_PARA_ERRO.get(codigo))
