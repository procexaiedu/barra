"""Camada e2e: o agente CONDUZ uma conversa multi-turn contra um cliente simulado.

Diferente do gate de seguranca (Camada 1, um turno isolado) e do shadow (Camada 2,
um ponto de decisao comparado head-to-head com o Vendedor humano): aqui o agente
dirige a conversa inteira, turno a turno, contra um cliente simulado ancorado num
caso real do corpus, e medimos ate onde ele leva o atendimento.

Linha de chegada (CONTEXT.md / dominio/atendimentos/service._decidir_transicao): a IA,
sozinha pela conversa com o cliente, leva o atendimento no maximo ate
`Aguardando_confirmacao` (ou `Confirmado`, se houver Pix externo). `Fechado`/`Perdido`
NUNCA saem da conversa com o cliente — sao Registro de resultado (modelo/Fernando) ou
timeout (cron). Logo "completou o atendimento" aqui = conduziu ate a confirmacao, que e
exatamente o trabalho que o Vendedor humano faz (ele tambem nao fecha no sistema).
"""
