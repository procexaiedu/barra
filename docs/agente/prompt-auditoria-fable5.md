# Prompt de auditoria integral do agente — Claude Fable 5

> Cole o bloco abaixo como prompt numa sessão do Claude Code rodando Fable 5, na raiz do repo `barra/`.
> Recomendado: effort `high` (ou `xhigh` se quiser a varredura mais profunda).

---

Estou auditando o agente conversacional do Barra (central de atendimento da Elite Baby) antes de avançar o piloto. Preciso que você confira, funcionalidade por funcionalidade, se a implementação está coerente com o domínio documentado — e corrija o que estiver errado. O resultado disso decide se o sistema está pronto para operar com clientes reais, então rigor importa mais que velocidade.

<contexto>
O repo é um monorepo: `api/` (FastAPI + LangGraph + ARQ, Python 3.12, psycopg3 puro), `interface/` (Next.js 16) e `infra/sql/` (migrations SQL sequenciais). O agente LangGraph vive em `api/src/barra/agente/` e roda dentro do worker ARQ (`api/src/barra/workers/`). O webhook da Evolution API entra por `api/src/barra/webhook/`.

Hierarquia de fonte de verdade, em ordem de precedência:
1. ADRs vigentes em `docs/adr/` (status accepted; `0015` está **rejected** — o LLM-judge nunca é gate, a camada determinística é o core).
2. `CONTEXT.md` (vocabulário e invariantes de domínio; se divergir de um ADR, o ADR vence).
3. `docs/agente/` (spec técnica do agente, docs 00–10) e `docs/mvp/` (produto).
4. O código. Quando código e doc vigente divergem, o **código é o suspeito** — mas leia o git log do arquivo antes de "corrigir": a divergência pode ser uma decisão posterior ainda não documentada. Nesse caso, reporte em vez de reverter.

Duas regras de calibração já decididas pelo Fernando (não re-litigar):
- `agente/prompts/persona.md` e `faq.md` são a verdade autoritativa de conduta. Em conflito entre fixture de eval e persona/FAQ, quem cede é a **fixture** — nunca edite persona/FAQ para fazer um teste passar.
- A IA nunca pergunta orçamento ao cliente (postura de luxo: quem tem tabela é ela). Cliente sem valor definido → ela dimensiona tempo e cota a tabela.
</contexto>

<escopo_da_auditoria>
Audite cada área abaixo. Para cada uma: leia a doc vigente, leia o código, leia os testes que a cobrem, e dê um veredito — `OK`, `divergência corrigida` ou `divergência reportada (decisão do Fernando)`.

**Fluxo do turno (webhook → resposta)**
1. Webhook Evolution: token, allowlist de instância, dedupe por `evolution_message_id`, parse de texto/áudio/imagem, distinção `fromMe` (IA vs modelo manual).
2. Debounce/coalescing: `pending:conv` + `debounce:conv`, `_job_id` SET NX first-wins, varredura de fallback, drain bounded do coordenador (MAX_DRAIN), teto de turnos/dia.
3. Grafo (6 nós): `prepare_context` → `intercept_disclosure` → `llm` → `tools` (loop ReAct) → `post_process` → `output_guard`. Confira o roteamento por `Command` (nenhum nó com `Command(goto=END)` pode ter aresta estática de saída) e o gate de pausa refeito no `post_process` (race de `ia_pausada`).
4. Humanização e envio (`workers/envio.py`): chunking, jitter, cancel-on-new-message, idempotência em `envios_evolution`, quote por trecho.

**Máquina de estados e fluxo interno/externo**
5. Transições: `Novo → Triagem → Qualificado → Aguardando_confirmacao → Confirmado/Em_execucao → Fechado/Perdido`. No máximo um atendimento aberto por par cliente-modelo; `#N` sequencial por modelo. Compare a máquina implementada com `docs/mvp/03`/`04` e `docs/agente/02` §11.
6. Fluxo **externo**: Pix de deslocamento de valor fixo, `pix_status` (validado/duvidoso/em_revisao), invariante "nunca trava por Pix" — duvidoso sinaliza no card e vai pra fila assíncrona do Fernando, sem handoff síncrono. Comprovante → `Confirmado` + `ia_pausada=true` (`modelo_em_atendimento`).
7. Fluxo **interno**: sem Pix; Aviso de saída (informativo, não muda estado) → Foto de portaria (qualquer imagem em `Aguardando_confirmacao` interno conta, sem vision no P0) → handoff implícito + `Aguardando_confirmacao → Em_execucao` automático. Timeout de 45 min contado de `aviso_saida_em` (não do horário combinado) → `Perdido` (`sumiu`), sem mensagem ao cliente.
8. A IA nunca negocia tipo de atendimento que a modelo não aceita (`tipo_atendimento_aceito[]`).

**Proatividade (crons)**
9. **Reengajamento**: toque único, só em `Triagem`/`Qualificado` com cotação apresentada, ~30 min após silêncio, dentro do horário de operação, **sem desconto**, não reseta o timeout de 24h, cancelável se o cliente responder antes. Flag começa desligada.
10. **Timeout longo**: 24h contadas da última mensagem do **cliente** → `Perdido` (`sumiu`), cancela bloqueio vinculado.
11. **Lembrete de fechamento**: gatilho é `bloqueios.fim` + tolerância (não a entrada em `Em_execucao`), reenvio em intervalo fixo até máximo de toques, depois handoff pro Fernando — **nunca** marca `Perdido` por silêncio; resposta da modelo é regex (`finalizado/fechado [valor]`), não NLP; não respeita quiet-hours.

**Venda e agenda**
12. Cotação: programa × duração de `modelo_programas`, MAX (não soma) de durações em combo, preço de tabela como teto, Fetiche como extra (sem duração; com preço = "+R$X", sem preço = incluso; nunca auto-soma o Valor final; recusa aberta do que não está na lista).
13. Desconto de fechamento: uma única contraproposta até o Piso de desconto; abaixo do piso escala `fora_de_oferta`; nunca expõe o piso; desconto nunca incide sobre o Pix; upsell de duração maior não é desconto.
14. Agenda: bloqueio prévio criado na qualificação dentro da Disponibilidade (gate só no **início**; o fim pode estourar a janela — Pernoite), advisory lock por modelo + EXCLUDE constraint contra sobreposição, sincronização do bloqueio no Registro de resultado. Conduta da IA: horário em **bloqueio** → desculpa pessoal, **nunca** revela outro cliente; fora da **Disponibilidade** → revela a volta e ancora a primeira data.

**Segurança e isolamento**
15. Isolamento por par: a IA na modelo A nunca lê dado do cliente com a modelo B; janela, contexto e observações escopados por (cliente_id, modelo_id). Painel-only nunca chega à IA: Dados cadastrais (RG/CPF/endereço residencial), tipo físico, Perfil físico preferido, nível do vendedor, Mapa de clientes.
16. Disclosure/jailbreak: classificador regex, 3 strikes de disclosure → escalada, jailbreak escala direto, reincidência em janela 24h via Redis, prova de humanidade roteada ao LLM.
17. Output guard (ADR 0016): scan léxico (auto-referência IA, fragmento de system, sigilo de agenda, dado de outra modelo) + judge AUP de saída; bloqueio → escalada + pausa.
18. Idempotência fim-a-fim: `turno_id` determinístico, `_executar_idempotente` + `call_idx` nas tools de escrita, dedupe de card por `card_message_id`, retry do ARQ sem duplicar envio.

**Handoff e comandos de grupo**
19. Coordenação por modelo (2 participantes), cards acionáveis, comandos `IA assume`, `fechado [valor]`, `perdido [motivo]`, quote de card dispensa `#N`, comando da modelo efetivo imediatamente, `fechado` sem valor / `perdido` sem motivo pedem complemento e não alteram nada, devolução pra IA só explícita.

**Cache e custo**
20. Invariante de prefixo: tools + BP_GERAL byte-idênticos entre modelos; BP_MODELO/BP_JANELA por modelo; contexto dinâmico e reminder voláteis sem cache_control; ordem dos breakpoints por TTL. Qualquer interpolação por modelo dentro do BP_GERAL quebra o cache global — procure por isso.
21. Injeção de data/hora no contexto: confira se `prepare_context` injeta data **e hora** em America/Sao_Paulo (há histórico de bug de só-data em UTC); se ainda só injeta data, é divergência a corrigir.
</escopo_da_auditoria>

<metodo>
Trabalhe por área, mas paralelize: despache subagentes de leitura para mapear áreas independentes simultaneamente e siga trabalhando enquanto rodam. Para cada divergência que encontrar, antes de corrigir, faça um subagente cético com contexto limpo tentar **refutá-la** lendo só doc + código — só corrija o que sobreviver à refutação. Divergência entre dois docs (sem código errado) → corrija o doc subordinado conforme a hierarquia de precedência; divergência que exige decisão de produto → reporte, não decida.

Antes de reportar qualquer item como verificado, audite a afirmação contra um resultado concreto de ferramenta desta sessão (arquivo lido, teste rodado, grep). Não reporte nada como "confirmado" sem evidência apontável; se algo ficou sem verificar, diga explicitamente.
</metodo>

<correcoes>
Para defeitos confirmados: corrija direto, com a mudança mínima — sem refactor adjacente, sem melhoria especulativa, sem tocar persona.md/faq.md para acomodar teste. Cada correção precisa de um teste que a reproduz (vermelho antes, verde depois) em `api/tests/` ou fixture em `api/evals/regressao/`. Siga o estilo do código existente.

Gate de verificação ao final: `make lint`, `make typecheck` e `make test` em `api/` (e `pnpm lint` + `pnpm build` em `interface/` se tocar frontend). Tudo verde antes de declarar concluído; se algo falhar, relate a saída em vez de contornar.
</correcoes>

<fronteiras>
Regras duras — nenhuma exceção sem autorização explícita do Fernando, frase a frase:
- **Nada que gaste crédito Anthropic real**: não rode `make test-llm`, `make evals` com chamadas vivas, nem o agente ao vivo. A suíte permitida é `make test` (exclui `needs_key`).
- **Nada que toque produção**: sem `make migrate`, sem mutação no banco de prod, sem mensagem real no WhatsApp, sem deploy/redeploy/restart no Portainer, sem `git push`. Os testes `needs_db` apontam para o banco real com rollback — pode rodá-los, mas só leitura+rollback; qualquer outra escrita em prod é proibida.
- Correções ficam em commits **locais** na branch atual. Não abra PR nem empurre.
- Se encontrar algo grave que pareça exigir ação em prod (dado corrompido, migration faltando), **reporte e pare** nesse item.
</fronteiras>

<relatorio_final>
Sua última mensagem é a primeira coisa que vou ler depois de horas — escreva-a como re-apresentação, não como continuação do seu fio de trabalho. Abra com o desfecho em uma frase: quantas áreas auditadas, quantas OK, quantas corrigidas, quantas aguardando minha decisão. Depois, por área: veredito e, quando houver divergência, o que a doc manda, o que o código fazia, o que você mudou (com `arquivo:linha`) e qual teste prova. Itens "decisão do Fernando" vêm por último, cada um com as opções e a sua recomendação. Prosa completa, termos por extenso, sem encadeamento de setas nem rótulos que você inventou no meio do caminho. Feche com a saída do gate de verificação.
</relatorio_final>

Você está operando de forma autônoma: para ações reversíveis e locais que decorrem deste pedido, prossiga sem perguntar; pare apenas nas fronteiras acima ou quando faltar input que só eu tenho. Não encerre o turno com plano ou promessa — execute até o relatório final.
