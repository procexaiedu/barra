"""Contexto Graduacao: torna COMPUTAVEIS os quatro criterios de graduacao do piloto (ADR-0034).

O ADR fixa os criterios (>=100 conversas completas conduzidas pela IA; zero incidente critico
nao-contido; taxa do gate estavel ou caindo; conversao >= 80% do baseline do vendedor) e registra
como divida que "graduacao nao e computavel hoje -- a decisao e feita a olho". Este contexto paga
a parte pagavel dessa divida: le o banco e devolve os quatro numeros com procedencia, mais os
GAPS do que nao e derivavel do dado atual.

Read-only sobre o dominio (nao escreve nada; a unica tabela propria, `graduacao_baseline`, e
alimentada por INSERT manual autorizado). Nao decide a graduacao: o relatorio diz o que os dados
dizem, e a decisao continua humana -- mesma divisao de trabalho do `rollback_watch`, que alerta
mas nunca pausa a modelo sozinho.

Exposicao: CLI `make graduacao` (-> `python -m barra.dominio.graduacao`). Sem rota HTTP no P0 --
o consumidor e o dev na revisao do piloto, e endpoint pediria tela no painel.
"""
