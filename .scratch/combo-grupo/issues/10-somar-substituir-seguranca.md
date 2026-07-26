# 10 — Somar × substituir × segurança

**O que construir:** a conduta precisa distinguir três pedidos que hoje recebem a mesma resposta (`"Só eu amor"`) e que **não são a mesma coisa**:

- **Somar** — *"tem mais amigas?"*, *"preciso de mais 3"*, *"somos 4 aqui"*, *"meu amigo quer uma também"*. Destrava a ferramenta. A agência fatura N programas e a **Modelo do canal não perde** a venda dela.
- **Substituir** — *"me indica outra"*, *"tem uma mais nova?"*. **Não** destrava; segue a recusa de sempre. Existe no corpus (*"Alguma amiga do seu perfil pra indicar pra hoje?"*), mas é ~1 ocorrência clara em 33.400 mensagens — não justifica motivo de escalada próprio. **`cross_modelo_fishing` é removido** do vocabulário de escalada.
- **Segurança** — *"atende sozinha?"*, *"tem mais gente aí?"*. **Nunca** destrava. E aqui está a parte mais delicada: se destravasse, a IA responderia uma sondagem de privacidade revelando que há outra mulher no mesmo prédio — o pior vazamento possível.

O critério que separa os três **não é a palavra**, é o complemento. No corpus, "sozinha" aparece sempre ancorado no local (*"vc atende na sua casa sozinha??"*, *"você atende sozinha no local?"*), enquanto os pedidos de amiga **sempre nomeiam a amiga** (*"tem alguma amiga?"*, *"você atende com amiga?"*, *"tem umas amigas?"*).

**Redação decidida (25/07):** a resposta à pergunta de segurança passa a ser

```
Só eu e você amor

Bem discreto rs
```

Uma palavra a mais que a fala de hoje, e o **objeto da afirmação muda do prédio para o encontro**. `"Só eu amor rs"` afirma algo sobre o mundo (sou a única aqui) — fecha a porta e vira mentira no dia em que o combo existir. `"Só eu e você"` afirma sobre o encontro (ninguém mais entra nisso), que é exatamente o medo de quem faz essa pergunta: armação, terceiro, não estar sozinho com ela. Não afirma nem nega a existência de outra mulher, então o cliente que sondava amiga por via indireta emenda (*"não tem nenhuma amiga aí?"*) e **aí sim** destrava a ferramenta.

⚠️ **`"Só eu amor rs"` aparece DUAS vezes no prompt e as duas ocorrências divergem a partir daqui:**

- em `<menage>`, na pergunta de **segurança** → vira `"Só eu e você amor"`;
- em `<fora_do_cardapio>`, no pedido de **indicação** (*"me indica outra"*) → **permanece** `"Só eu amor rs"`, porque substituir não destrava. Nessa linha muda apenas a escalada (`cross_modelo_fishing` sai).

Não unificar as duas.

`<menage>` permanece intacto: amiga **no mesmo quarto** continua sendo **Escalada** (`outro`). Combo é uma mulher **por pessoa**, não duas para o mesmo homem.

**Bloqueado por:** 06 (a ferramenta precisa existir para se decidir o que a destrava).

**Nota de escopo:** os critérios *negativos* — que "atende sozinha?" e "me indica outra" **não** destravam — foram movidos para o **06**, porque o guard-rail tem que entrar junto com a capacidade que ele contém, não num ticket posterior. Este ticket cobre o **refino**: a redação nova, a remoção do `cross_modelo_fishing` e a cobertura de variações.

**Status:** ready-for-agent

- [ ] Variações de somar e de substituir cobertas além das frases literais já testadas no 06
- [ ] "atende sozinha?" / "tem mais gente aí?" seguem sem destravar, em qualquer variação
- [ ] `<menage>` passa a usar "Só eu e você amor" / "Bem discreto rs" na pergunta de segurança
- [ ] `<fora_do_cardapio>` mantém "Só eu amor rs" na indicação — as duas falas NÃO são unificadas
- [ ] Cliente que emenda "não tem nenhuma amiga aí?" depois da resposta de segurança destrava a ferramenta
- [ ] `cross_modelo_fishing` removido do prompt e do vocabulário de escalada, sem quebrar os mapeamentos existentes
- [ ] `<menage>` segue escalando amiga no mesmo quarto
- [ ] Um preço por vez continua valendo com várias convidadas na mesa
- [ ] Desconto pedido sobre o valor de uma convidada não gera contraproposta e escala `fora_de_oferta`
- [ ] Coberto no rig de conduta (`test_conduta.py` / `test_conduta_fiel_llm.py`)
