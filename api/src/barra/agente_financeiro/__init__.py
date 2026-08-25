"""Agente financeiro (spec 0005): a IA ingestora dos Grupos financeiros das modelos.

A superficie publica do modulo sao TRES funcoes: `processar_evento_do_grupo` (a porta unica — um
evento do grupo entra, os efeitos saem; mensagem, delecao, reacao e edicao sao ramos dela),
`fechamento_da_modelo` (o extrato derivado, que nasce de leitura no painel, nao de mensagem) e
`cobrar_pendencias_do_grupo` (a rotina diaria da manha — a unica que nasce de RELOGIO: ela decide
e posta, e quem responder cai de volta na porta unica). Webhook, cron, testes e o futuro replay do
export do grupo entram por elas; nada mais deste pacote deve ser chamado de fora.

`processar_mensagem_do_grupo` e `processar_delecao_do_grupo` seguem exportadas como WRAPPERS finos
da porta unica — a entrada historica dos chamadores de hoje, mantida para que a generalizacao da
porta nao custe um mutirao de renomeacao. Codigo novo chama `processar_evento_do_grupo`.
"""

from barra.agente_financeiro.porta import (
    EdicaoNoGrupo,
    EventoDoGrupo,
    ReacaoNoGrupo,
    ResultadoDaPorta,
    fechamento_da_modelo,
    processar_delecao_do_grupo,
    processar_evento_do_grupo,
    processar_mensagem_do_grupo,
)
from barra.agente_financeiro.rotina import ResultadoDaRotina, cobrar_pendencias_do_grupo

__all__ = [
    "EdicaoNoGrupo",
    "EventoDoGrupo",
    "ReacaoNoGrupo",
    "ResultadoDaPorta",
    "ResultadoDaRotina",
    "cobrar_pendencias_do_grupo",
    "fechamento_da_modelo",
    "processar_delecao_do_grupo",
    "processar_evento_do_grupo",
    "processar_mensagem_do_grupo",
]
