"""A pergunta minima do Agente financeiro (spec 0005, ticket 03).

O agente e ingestao silenciosa: grava calado o que esta completo e **so abre a boca quando falta
o minimo do registro** (modelo + valor + data — ADR-0043). Duas regras moldam o texto:

* **Uma mensagem, so o buraco.** Nada de formulario ("me manda local, duracao, forma de
  pagamento"): campo opcional que nao foi dito nao vira pergunta, e forma de pagamento NUNCA e
  perguntada aqui — ela e Pendencia e a cobranca dela e consolidada, de manha (ticket 10). Uma
  pergunta por venda incompleta, no momento do anuncio, e o teto.
* **Pergunta objetiva = pergunta que uma palavra responde.** "Quanto foi?" se responde com "600";
  "'fran loira' é quem?" se responde com um nome. E o que faz a resposta poder completar o
  registro sozinha, sem o grupo ter que repostar o anuncio inteiro.

Por isso `nome_ambiguo` (dois cadastros com o mesmo nome) NAO gera pergunta: repetir o nome nao
desempata nada — aquilo e erro de cadastro, some no painel e nao no grupo.
"""

from __future__ import annotations

from typing import Literal

Falta = Literal["valor", "modelo"]
"""O que impede o registro. Ordem tambem: o valor vem primeiro na frase por ser o dado que o
grupo mais esquece."""

PREFIXO_DA_PERGUNTA = "❓ Só falta saber: "
"""Assinatura visual da pergunta minima, do mesmo naipe do "✅ Registrei:" do recibo — de relance
o grupo ve se o agente registrou ou se esta esperando algo."""


def montar_pergunta_minima(
    *,
    faltas: tuple[Falta, ...],
    cliente: str | None = None,
    nomes_desconhecidos: tuple[str, ...] = (),
    por_modelo: bool = False,
) -> str | None:
    """A UMA mensagem que o agente posta quando o anuncio nao fecha o minimo.

    `None` quando nao ha nada que uma resposta curta resolva — e o sinal de que a conduta certa
    e o silencio.

    `por_modelo` = o anuncio tem duas participantes: ali a pergunta pelo valor precisa dizer
    "cada uma", senao a resposta ("1200") volta como total e cada mulher recebe o dobro.
    """
    partes: list[str] = []
    if "valor" in faltas:
        cauda = "para cada uma" if por_modelo else ""
        alvo = f"o atendimento do Cliente {cliente}" if cliente else "esse atendimento"
        partes.append(" ".join(p for p in ("quanto foi", cauda, alvo) if p) + "?")
    if "modelo" in faltas and nomes_desconhecidos:
        quem = " / ".join(nomes_desconhecidos)
        partes.append(f"“{quem}” é quem?")
    if not partes:
        return None
    frase = partes[0] + "".join(f" E {resto[0].upper()}{resto[1:]}" for resto in partes[1:])
    return f"{PREFIXO_DA_PERGUNTA}{frase}"
