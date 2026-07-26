# 06 — Cliente pede amiga e recebe uma oferta real (interno)

**O que construir:** o cliente escreve *"tem mais amigas? preciso de mais 3"* e, em vez de `"Só eu amor, não tenho amigas aqui não rs"`, recebe uma oferta verdadeira — nome, foto e preço de cada **Modelo convidada** que **de fato** pode atender naquela janela. Se houver menos do que ele pediu, ela oferece o que tem sem prometer o resto. Se não houver ninguém, ela responde sem fechar a porta e segue vendendo o programa dela.

O princípio: **a LLM fala, o determinístico decide**. Uma ferramenta de leitura nova (irmã de `consultar_agenda`) devolve o conjunto elegível já resolvido; a IA nunca escolhe quem está livre nem calcula preço. E o gate é **estrutural**: fora dessa chamada, nenhuma outra modelo entra no contexto — nas conversas que não pedem amiga, a IA literalmente não tem o dado para vazar, exatamente como o `<local_de_encontro>` que só aparece a partir de `Qualificado`.

Elegibilidade, toda em SQL:

- `status = 'ativa'` — `pausada`/`inativa` nunca entram (o freio manual é soberano)
- **mesmo endereço de encontro** da modelo do canal (hoje as duas dividem o `Vitória Hotel Residence Newport`, unidades diferentes)
- **Disponibilidade** cobrindo a janela pedida
- nenhum **Bloqueio** ativo sobrepondo, respeitando o buffer de preparo (ADR 0025)
- o cliente **não pode** já ter **Atendimento** aberto com aquela convidada
- teto de itens no retorno, como o cap de bloqueios de `consultar_agenda`

Cada convidada sai com o **Preço de tabela dela**, calculado a partir dos programas dela — nunca o preço do canal. Só **interno** neste ticket; externo é o 11. Nunca remoto. Nasce atrás de flag de settings **desligada**.

Esta é a fatia que torna o #36 vendável.

**Bloqueado por:** 04 (foto de perfil).

**Status:** ready-for-agent

- [ ] Pedido de somar ("tem mais amigas?", "preciso de mais 3", "somos 4") produz oferta com nome, foto e preço
- [ ] **"atende sozinha?" / "tem mais gente aí?" NÃO destravam a ferramenta** — a resposta é "Só eu e você amor" / "Bem discreto rs" (decidida, ver ticket 10)
- [ ] **"me indica outra" / "tem uma mais nova?" NÃO destravam** — substituir não é somar
- [ ] Convidada `pausada` ou `inativa` nunca aparece
- [ ] Convidada em outro endereço não aparece no interno
- [ ] Convidada fora da Disponibilidade, com Bloqueio sobreposto ou dentro do buffer não aparece
- [ ] Convidada com Atendimento já aberto com aquele cliente não aparece
- [ ] Preço devolvido é o da tabela da convidada, e a IA não faz nenhuma conta
- [ ] Pool menor que o pedido oferece o que tem, sem prometer o resto
- [ ] Pool zero não produz "não tenho amigas" nem encerra a conversa
- [ ] Contexto padrão segue sem qualquer menção a outra modelo quando a ferramenta não é chamada
- [ ] Flag de settings desliga a oferta sem deploy
- [ ] Testes `needs_db` no molde de `test_extrair_inline.py`, sem `needs_key`
- [ ] Canário de isolamento estendido: a ferramenta devolve disponibilidade da convidada e nunca o sentinela do par (cliente × convidada)
