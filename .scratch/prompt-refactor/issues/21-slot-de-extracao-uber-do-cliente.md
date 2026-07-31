# 21 — Quando o uber é do cliente, o Pix não deveria ser pedido

**What to build:** a conduta diz que, se o cliente chama o uber ida e volta dele, quem paga é ele e o Pix não entra — é um ou outro, nunca os dois. Mas o Pix é solicitado deterministicamente em todo atendimento externo, e não existe campo na extração que registre "o uber é dele". A conduta manda uma coisa e o sistema faz outra, e o cliente pode receber um pedido de Pix por um uber que ele já está pagando.

**Não é conserto de prompt** — é campo que falta. Por isso está fora do plano de reescrita.

**Decisão tomada (dev, 31/07):** **somente a modelo pede o uber, por segurança.** Vale a segunda
opção — a conduta para de aceitar o uber do cliente. Sem campo de extração, sem condição no trilho
do Pix: o Pix determinístico do externo passa a estar sempre certo, porque não existe mais o caso
em que ele estaria errado.

**Blocked by:** None.

**Status:** ready-for-agent

- [ ] a conduta deixa de aceitar o uber do cliente — o "pode deixar" do `<tipos_de_encontro>` sai
- [ ] a recusa vem com fala de substituição (lição do incidente #36: proibir sem dar a fala é o que
      cria o bug), e a insistência tem saída definida
- [ ] o eco do `persona.md` e qualquer outro site que trate o uber do cliente acompanham
- [ ] `CONTEXT.md`, verbete **Pix de deslocamento**, deixa de dizer que não há Pix quando o cliente
      chama o próprio uber — hoje o texto contradiz esta decisão
- [ ] a decisão de 10/07 (Fernando, grupo de testes) fica registrada como superada, com data

**A redigir junto com o Fernando:** a fala revela a razão de segurança ou não? O caso vizinho — ele
querer buscá-la de carro — é explicitamente sem dar a razão ("redirecione pros formatos que
existem"). Manter as duas coerentes é preferível a inventar uma exceção.

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
