"""Vocabulario do CATALOGO de servicos: o que e presencial e o que e REMOTO.

O catalogo global (`barravips.programas`) nao tem coluna que diga a natureza do servico -- so
`nome` e `categoria` livres, preenchidos pelo painel. A unica distincao que o codigo precisa
tirar dele e binaria e vem do ADR-0021: a vídeo chamada e o UNICO servico remoto; todo o resto e
encontro presencial. Enquanto isso morava em `agente/persona.py`, so o agente conseguia fazer a
pergunta -- `dominio/` nao importa `barra.agente` (dominio/CLAUDE.md) -- e a leitura de tabela do
dominio tratava a linha da chamada como se fosse mais um pacote presencial da mesma duracao. Foi
exatamente esse o buraco de 11/08/2026: cadastrada a chamada da Catarina em 0.5h e 1h, a duracao
passou a ter DOIS precos, e todo mundo que exige "um preco so" (escada de desconto, base do
patamar) devolveu None -- a escada morreu na 1h, o pacote que mais vende.

Mora em `core/` por isso: e a camada que `dominio/`, `agente/` e `workers/` podem importar sem
inverter a hierarquia. Sem DB, sem settings, sem IA.
"""

from barra.core.texto import normalizar


def e_video_chamada(nome_do_programa: str) -> bool:
    """A linha do `<programas>` e a vídeo chamada (o único serviço REMOTO — ADR-0021)?

    O gate do prompt sempre foi por NOME ("ela só existe se estiver nos seus <programas>", lido
    pelo próprio LLM na tabela do BP_MODELO); aqui o mesmo julgamento vira dado, sobre as mesmas
    linhas. O catálogo é curado e a palavra da operação é "chamada" (CONTEXT.md "Vídeo chamada",
    card "Hora da vídeo chamada"): "Vídeo chamada", "Videochamada" e "Chamada de vídeo" casam
    todas pelo substring, com ou sem acento (`normalizar`). Cadastro que a batize sem a palavra
    ("Vídeo", só) NÃO casa — nesse caso a cauda a trata como ausente e a modelo recusa o que
    vende; é o lado do erro que não promete ao cliente uma chamada que a tabela não tem. É o
    mesmo predicado que a migration 20260811214743 usa como chave (`lower(nome) LIKE '%chamada%'`)
    para não criar um segundo programa de chamada no catálogo.

    SITE ÚNICO do predicado. Consumidores, em duas famílias:
    - PROMPT (via `agente/persona.py`, que reexporta daqui): o gate `<sem_video_chamada>` da cauda,
      o `<fetiches>` (fetiche pago só existe em programa PRESENCIAL — a chamada de 60min da
      Catarina, R$600, passaria no filtro de duração e viraria "Vídeo chamada (1h) | R$1.000") e o
      `_menu_primeira_cotacao`;
    - PREÇO (via `dominio/atendimentos/service._linhas_da_duracao`, parâmetro
      `apenas_presenciais`): quem pergunta "qual é O pacote presencial desta duração" filtra a
      linha remota; quem JULGA um atendimento já vendido, não — ver a docstring de lá.
    """
    return "chamada" in normalizar(nome_do_programa)
