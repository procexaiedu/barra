# 004 — Qualificação por videocall paga (R$ 250) antes de marcar encontro

- **Origem**: screen recording `docs/modelos/WhatsApp Video 2026-05-27 at 18.08.15 (2).mp4` (14.5s, 14 frames @1fps).
- **Modelo-tipo**: morena (chat etiquetado "Cl David Dupla Ha...").
- **Cotação**: R$ 900/1h presencial + R$ 250 por **videocall de 15min** (vendida como qualificação anti-trote / "vai me conhecer melhor").
- **Resultado**: videocall paga e feita (Pix R$ 250 confirmado). Atraso da modelo ("terminando meu cabelo"), cliente tentando manter combinado; depois cliente pede "anúncio das amigas" (sinal de interesse em dupla). Conversa segue.
- **Por que é ouro**: documenta o **padrão de videocall paga como qualificação** (preventiva contra trote, alta margem, sem deslocamento) que **não está no `CONTEXT.md`** ainda. Mostra como vender a videocall ("Vai me conhecer melhor amor"), como pedir o Pix, como confirmar o comprovante via encaminhamento, e como sustentar engajamento quando o atendimento atrasa.

---

## [abertura] — qualificação rápida
```
11:13  CLIENTE: Bom dia
11:13  CLIENTE: Clara?
11:14  MODELO:  Ola bom dia
11:14  CLIENTE: Tudo bem?
11:14  CLIENTE: Vi um anúncio
11:14  CLIENTE: Gostaria de mais informações
11:16  CLIENTE: Está ocupada?
11:17  MODELO:  Bem e você ?
11:17  MODELO:  Livre amor
11:17  MODELO:  Estou na barra
11:17  MODELO:  900 1h
```
> Cliente pergunta por nome ("Clara?"). Modelo **não confirma o nome explicitamente** — responde "Bem e você ?" + "Livre amor" e já entrega cotação. Padrão de 4 bolhas curtas: cumprimento + status + localização + preço. Sem confirmar identidade reduz risco de extração de dado.

## [upsell-videocall] — vende, precifica, qualifica
```
11:18  CLIENTE: Aonde na Barra?
11:19  CLIENTE: Faz vídeo chamada?
11:20  MODELO:  Sim
11:20  MODELO:  250
11:20  CLIENTE: Está livre?
11:20  MODELO:  Sim
11:20  CLIENTE: ↳ quote: "250"
                Qnto tempo?
11:20  MODELO:  15min
11:20  CLIENTE: Podemos?
11:21  MODELO:  Vou enviar meu Pix
11:21  CLIENTE: Ok
11:21  CLIENTE: O que rola na vídeo?
11:21  MODELO:  Vai me conhecer melhor amor ❤️
11:21  CLIENTE: Top
11:21  CLIENTE: Podemos conversar?
11:21  CLIENTE: Pode mandar
```
> **Padrão videocall paga**:
> - **Não dá endereço** ("Aonde na Barra?" é ignorado em favor da próxima pergunta).
> - **Cota em 2 bolhas separadas** ("Sim" + "250") — não junta "Sim, 250" numa só.
> - **Tempo só quando perguntado** ("15min" depois do quote de 250).
> - **"Vai me conhecer melhor amor ❤️"** como pitch ambíguo (não promete nudez nem nega), absorve "O que rola na vídeo?" sem detalhar.
> - **"Vou enviar meu Pix"** antes do cliente pedir — assume o fechamento.

## [gap-tempo] — cliente espera, modelo demora a mandar
```
11:25  CLIENTE: ?
12:17  CLIENTE: Pelo visto não está podendo neh
12:46  MODELO:  [CHAVE-PIX] [OPERADORA]
12:46  MODELO:  Aqui meu amor ❤️
12:46  CLIENTE: ?
12:47  MODELO:  Vamos fazer a vídeo, estou animada 😄
```
> Modelo demora ~1h25 entre "Vou enviar meu Pix" e enviar a chave. Cliente avisa "Pelo visto não está podendo neh" — desistência iminente. Modelo recupera **sem se desculpar pela demora**: manda Pix + "Aqui meu amor ❤️", depois reforça vontade ("Vamos fazer a vídeo, estou animada 😄"). **Nada de "desculpa demorei"** — evita reabrir o problema.

## [pix-confirmacao-encaminhada]
```
12:47  CLIENTE: Esse é o pix?
12:48  MODELO:  Sim
12:49  CLIENTE: Feito
12:49  CLIENTE: Caiu aí?
12:51  MODELO:  Manda o comprovante por gentileza.
12:51  MODELO:  ↳ (encaminhada de outro chat) "Caiu aí?"
                [referência: "Cl David Dupla Hanna 2 E Bianca 3 Pagou..."]
12:51  MODELO:  Vou conferir
12:51  CLIENTE: [COMPROVANTE-PIX R$ 250,00]
                De: [CLIENTE] → Para: [OPERADORA] / [INSTITUICAO]
                Chave Pix: [CHAVE-PIX]
```
> **Pede comprovante mesmo com "Feito"** — não confia em alegação. Encaminha a pergunta de outro chat (rótulo "Cl X Dupla Y E Z Pagou..." revela uso de etiquetas de chat para classificar pagamento). **Conferência explícita** ("Vou conferir") cria expectativa de validação.

## [atraso-modelo] — depois da videocall paga, cabelo
```
13:05  MODELO:  Só estou terminando meu cabelo
13:10  CLIENTE: ?
13:11  MODELO:  5min
13:11  MODELO:  😊😊😊
13:11  CLIENTE: Vou ter q sair jaja
13:16  CLIENTE: ?
13:18  MODELO:  Chamando
13:19  CLIENTE: Vamos?
13:19  MODELO:  Vou te chamar de outro número
13:19  CLIENTE: Ok
```
> **Padrão consistente com persona** (`CONTEXT.md`): quando atrasa, dá desculpa pessoal coerente ("terminando meu cabelo"), **não revela razão real** (que pode ser outro atendimento, conferindo pagamento, demora operacional). "Vou te chamar de outro número" — fallback técnico (instância secundária / outro Evolution) sem explicar.

## [pos-videocall] — cliente pede amigas, modelo redireciona
```
13:36  CLIENTE: Oi
13:40  CLIENTE: Me passa o anúncio das suas amigas por gentileza
13:42  MODELO:  Para eu seria ? (editada)
13:44  MODELO:  Quer fazer mais vídeo ?
```
> Cliente pediu "anúncio das amigas" — sinal de interesse em dupla **mas com outra modelo**. Modelo **redireciona pra si própria**: "Para eu seria ?" (= se for pra mim seria, e quanto?) + "Quer fazer mais vídeo ?". Tenta segurar o cliente na sua conta — **não fornece contato de outras modelos** mesmo se pedido (proteção da carteira própria).

---

## Insights operacionais

1. **Videocall paga como qualificação** (~R$ 250 / 15min) — alta margem, sem deslocamento, filtra trote (quem paga 250 numa videocall é cliente real).
2. **Cota videocall em 2 bolhas separadas** ("Sim" / "250") — separa confirmação de faz/não faz do preço.
3. **"Vai me conhecer melhor amor ❤️"** como pitch ambíguo da videocall — vende sem prometer nudez nem negar.
4. **"Vou enviar meu Pix" antes do cliente pedir** — assume fechamento.
5. **Manda Pix sem se desculpar por demora**, mesmo depois de "Pelo visto não está podendo neh" — recupera com "Aqui meu amor ❤️" + reforço de vontade.
6. **Pede comprovante mesmo com "Feito"** — não aceita alegação.
7. **Rótulo de chat marca status de pagamento** ("Cl X ... Pagou ..." aparece quando modelo encaminha — sugere convenção operacional de gerenciamento manual).
8. **Desculpa de atraso é pessoal e coerente com horário** ("terminando meu cabelo" às 13h) — nunca revela razão real.
9. **"Vou te chamar de outro número"** como fallback técnico sem explicar.
10. **Cliente pedindo amigas é redirecionado pra si mesma** — "Para eu seria ? / Quer fazer mais vídeo ?".
11. **Não confirma o nome perguntado pelo cliente** ("Clara?" não é respondido) — reduz vinculação identidade-conta.
