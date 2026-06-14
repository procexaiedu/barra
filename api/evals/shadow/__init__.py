"""Camada 2 — shadow head-to-head contra o Vendedor humano (advisory, NAO-blocking).

O proxy mais direto de "a IA substitui o Vendedor": pega os turnos reais do corpus
(`corpus.turnos`, as 4 modelos eb01-04) num ponto de decisao, roda o grafo REAL (Moeda B,
credito — §0) sobre o mesmo contexto que o humano viu, e compara a resposta da IA com o que o
humano DE FATO fez. Pontua por fidelidade comportamental, NUNCA por conversao (judge de desfecho
e quase-acaso, κ=0.07 — doc 11 §2). Ver README.md.
"""
