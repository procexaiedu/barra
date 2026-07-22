## Sintoma

Atendimento **#10** da Tatiane (cliente 5519989375454, 21/07 ~21:34). Depois de negar o pernoite, a IA ofereceu e cotou um pacote de 3h **que não existe na tabela, pelo preço da 1h**:

- trace `fc209c69e55b6474039acd0bae3d9b54` → "Haha quem sabe a gente combina um tempo maior / **3h 800 no meu local**, podemos fechar 21h às 00h ou 22h às 01h"
- trace `bbfc07a7e19fcef26837349574db676b` → "**800 3h no meu local** / 22h às 01h confirmado amor ?"

Catálogo real da Tatiane: só **1h** (Completo R$800, Normal R$400). O modelo violou a regra existente do prompt ("NUNCA invente um preço pra uma duração que não está na sua tabela", `regras.md.j2` L58) e vendeu 3h por R$267/h. O cliente topou na hora — se não fosse o cancelamento do piloto, fechava 3h subprecificado.

## Esperado (Fernando, 21/07 ~21:50, via print na sessão — sem inbox)

> "3h 800 / lembrando que **o valor mínimo de 1h seria 300**. Então **o ideal a cobrar é 900,00**"

Regra de negócio: piso de **R$300/hora** — um pacote de 3h nunca sai por menos de R$900.

**PERGUNTAS PRO FERNANDO:**
- O piso de R$300/h é global (toda modelo) ou por modelo?
- Prefere resolver por **cadastro** (criar 2h/3h/pernoite na tabela da Tatiane com preços reais — aí a IA nunca precisa calcular) ou por **regra de piso** que a IA aplica quando improvisa um período fora da tabela? (as duas coisas juntas também valem: cadastro cobre o normal, piso é a rede de segurança)

## Contexto interno (trace)

- extração (`fc209c69`): `intencao=agendamento, tipo_atendimento=interno, data_desejada=2026-07-21`; em `bbfc07a7` já com `horario_desejado=22:00, duracao_horas=3`. O sistema registrou a venda de 3h sem nenhum guard de preço.
- `erros_tool` em `fc209c69`: `registrar_extracao` estourou o limite de 240 chars de `proxima_acao_esperada` (retry salvou — ruído recorrente, vale um clamp).
- O turno anterior (`aba07506`) já tinha prometido "posso combinar 3h ou mais" — a improvisação começou ali; a cotação errada foi a consequência.

## Hipótese de código (confirmar)

- ~ `agente/prompts/regras.md.j2` L58 + `<sobe_o_ticket>` L62-70: a proibição de inventar preço existe, mas o caminho "ofereça período maior" sem pacote maior na tabela deixa o modelo sem saída honesta — ele improvisa. Falta: (a) instrução de fallback quando a tabela não tem o período (ancorar no que existe ou escalar), (b) a regra do piso R$300/h se Fernando optar por ela.
- ~ Guard determinístico (`agente/nos/output_guard.py` ou validação na extração): `valor_acordado / duracao_horas < piso` deveria travar/escalar antes de sair a bolha — regra de prompt sozinha já provou que fura.
- ~ Cadastro: mesma dependência da issue do pernoite (criar as combinações reais da Tatiane).
- ~ Menor: clamp/truncate de `proxima_acao_esperada` antes do invoke (`agente/ferramentas/extracao.py`) pra matar o retry por >240 chars.

trace_ids: `fc209c69e55b6474039acd0bae3d9b54`, `bbfc07a7e19fcef26837349574db676b`
