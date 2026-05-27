# 002 — Dupla com amiga, cliente escolhe uma, pagamento depois (interno)

- **Origem**: screen recording `docs/modelos/WhatsApp Video 2026-05-27 at 18.08.15.mp4` (29s, 29 frames @1fps).
- **Modelo-tipo**: morena de cabelo longo, atendimento **interno** ([APARTAMENTO]).
- **Cotação**: R$ 900/1h solo / R$ 1.600 dupla / "Aceito cartão".
- **Resultado**: fechado solo (cliente escolheu uma das duas) por R$ 900, pago via Pix **após** o atendimento. Cliente teve problema de interfone na portaria.
- **Por que é ouro**: tem **upsell de dupla via "estou com uma amiga, você curte?"**, **tabela dupla clara**, **manejo do cliente que recua** ("vou ter que escolher uma então"), **fluxo de portaria com interfone quebrado**, e **Pix pós-atendimento** (não trava o fluxo).

---

## [abertura-dia-anterior]
```
Sáb 04:52  CLIENTE: Olá, vendo você no Barra Vip's
Sáb 04:52  CLIENTE: Ta online?
Sáb 07:41  MODELO:  Oii bom dia
Sáb 07:55  CLIENTE: Oie
Sáb 07:55  CLIENTE: Como funciona?
Sáb 10:21  MODELO:  Meu cachê 900 1h estou na barra da Tijuca
```
> Resposta atrasada (modelo dorme até 07:41, cliente volta 07:55, modelo responde 10:21). Mesmo assim a cotação é direta — "Meu cachê 900 1h estou na barra da Tijuca" numa linha só.

## [retomada-mesmo-dia]
```
Hoje 02:17  CLIENTE: Ta on?
     02:18  MODELO:  Oii
     02:18  MODELO:  Sim
     02:18  CLIENTE: Ondee
     02:18  CLIENTE: Exatamente na barra
     02:19  MODELO:  [ENDERECO-AV] [NÚMERO]
     02:19  CLIENTE: Chego 3h
```
> Cliente retoma de madrugada. Modelo confirma com 2 letras ("Oii / Sim") e já entrega endereço. Cliente diz horário sem perguntar disponibilidade — modelo aceita pelo silêncio.

## [upsell-dupla] — "estou com uma amiga, você curte?"
```
02:47  MODELO:  Estou com uma amiga
02:47  MODELO:  Você curte ?
02:48  CLIENTE: Curtir eu curto
                Se dou conta aí já é outra história kkk
02:48  MODELO:  Hahhaah
02:48  MODELO:  Vamoss
02:48  MODELO:  Ela já está aqui comigo (editada)
02:49  MODELO:  [FOTO-COLAGEM-DUAS-MODELOS]
```
> **Padrão de upsell de dupla**: oferece em duas mensagens curtas ("Estou com uma amiga" + "Você curte ?") em vez de uma frase longa. Reage ao "kkk" do cliente com "Hahhaah" (não com "kkk" puro — consistente com banimento). **Manda colagem visual antes de cotar dupla** — vende com imagem, depois com preço.

## [cotacao-dupla] — tabela completa
```
02:49  CLIENTE: Msm preço?
                Se for mais to fora... vou conseguir fazer valer não hahah
02:49  MODELO:  Valor individual amor
02:50  MODELO:  Só eu 900
02:50  MODELO:  Nós duas 1600
02:50  MODELO:  Aceito cartão
02:50  MODELO:  🙂🙂
```
> **Tabela em 4 mensagens curtas**: "Valor individual" (sinaliza que é POR pessoa, não pacote), "Só eu 900" (referência sem dupla), "Nós duas 1600" (~10% desconto vs 2×900), "Aceito cartão" (remove fricção de pagamento), emoji de fechamento. Sem texto explicativo entre — deixa o cliente processar.

## [cliente-recua] — modelo aceita sem insistir
```
02:50  CLIENTE: Vou ter que escolher uma então 😅
02:51  MODELO:  Hahah
02:51  MODELO:  Você está chegando ?
02:54  CLIENTE: Chego 3:05
02:55  CLIENTE: [LOCALIZAÇÃO-AO-VIVO]
02:55  CLIENTE: Indo da zona sul
02:55  MODELO:  Vai ser nós duas ?
02:56  CLIENTE: Só 1
02:56  MODELO:  Ok
02:56  MODELO:  Te espero
```
> Cliente desiste da dupla → modelo **não insiste**, redireciona pra confirmar chegada ("Você está chegando?"). Mais tarde **reconfirma uma vez** ("Vai ser nós duas?") — recebe "Só 1" e fecha com "Ok / Te espero" sem reclamar nem oferecer desconto.

## [escolha-da-modelo] — "Pode ser ela / Sem problemas"
```
03:01  MODELO:  ↳ (encaminhada de [MODELO-AMIGA]) "Vou ter que escolher uma então 😅"
                Minha amiga está aqui
03:01  MODELO:  Rs
03:01  MODELO:  Pode ser ela
03:01  MODELO:  Sem problemas
03:04  CLIENTE: Qro vc
03:06  CLIENTE: Qual apto
03:07  MODELO:  AP [APARTAMENTO] Bloco [N]
```
> **Padrão raro mas importante**: a modelo **oferece a amiga como substituta** ("Pode ser ela / Sem problemas") — não force a venda pra si própria, deixa o cliente escolher. Cliente escolhe ela ("Qro vc"). Só depois disso entrega número do apartamento.

## [chegada-portaria] — interfone quebrado
```
03:07  CLIENTE: Okk
03:11  CLIENTE: Tá dando ocupado
03:11  CLIENTE: Liga p ramal 10
03:11  CLIENTE: Porteiro falou
03:12  MODELO:  Está entrando apé ? (editada)
03:12  CLIENTE: To na portaria
03:12  CLIENTE: Ning atende o interfone
03:13  CLIENTE: [FOTO-PORTARIA-EXTERNA]
03:14  MODELO:  Qual seu nome ?
03:14  CLIENTE: [CLIENTE]
03:15  MODELO:  Pede pra ligar aqui de novo
03:15  CLIENTE: Ok
```
> **Foto da portaria chega antes do nome**. Modelo pede nome **depois** da foto ("Qual seu nome?") — verifica visualmente antes de identificar. Quando interfone falha, instrui o porteiro a re-ligar ("Pede pra ligar aqui de novo") em vez de descer.

## [pix-pos-atendimento]
```
03:26  MODELO:  [CHAVE-PIX] [OPERADORA]
03:27  CLIENTE: [COMPROVANTE-PIX R$ 900,00]
                De: [CLIENTE] → Para: [OPERADORA] / [INSTITUICAO]
```
> **Pix depois do atendimento ter começado** (~13min depois da chegada na portaria). Operação não trava por Pix pendente — entra durante/depois. Consistente com `CONTEXT.md`: "o fluxo nunca trava por Pix". Chave Pix em **nome de terceira pessoa** ([OPERADORA] ≠ [MODELO]) — proteção da identidade fiscal da modelo.

---

## Insights operacionais

1. **Upsell de dupla em duas mensagens curtas** ("Estou com uma amiga" / "Você curte?") + colagem visual antes do preço.
2. **Tabela dupla padrão**: "Valor individual / Só eu X / Nós duas Y / Aceito cartão" + emoji — em 4 bolhas separadas, sem explicação no meio.
3. **Cliente que recua na dupla é aceito sem insistência** — modelo redireciona pra chegada, reconfirma uma vez, fecha.
4. **Oferta de amiga como substituta** quando dupla cai pra solo — protege a venda independente de quem o cliente escolher.
5. **Foto da portaria antes do nome** — verificação visual precede identificação.
6. **Pix pós-atendimento** com chave em nome de [OPERADORA] (não da modelo).
7. **"Hahah" / "Hahhaah" em vez de "kkk"** mesmo quando o cliente usa "kkk".
8. **Endereço completo só depois de cliente confirmar que vem** (entrega "Av..." só após "Ondee/Exatamente na barra").
9. **Apartamento + bloco** só depois do cliente bater na portaria conceitualmente ("Qual apto" → resposta).
