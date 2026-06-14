"""Contexto Observabilidade: visualizacao e AVALIACAO humana das respostas do agente.

Fernando ve cada resposta da IA (mensagens.direcao='ia') no contexto da mensagem do cliente e a
avalia (bom/ruim + nota + comentario). A avaliacao vira o ground-truth humano do eval (camada 3).
Painel-only (Depends(get_user) -> papel='fernando'); read-only sobre o dominio de atendimento +
escrita so na tabela avaliacoes_resposta_ia.
"""
