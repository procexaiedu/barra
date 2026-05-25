# Disponibilidade da modelo

Modelos não trabalham o mês inteiro (folga, data de início, ciclos). Introduzimos a
**Disponibilidade**: regras que definem quando uma modelo aceita ser reservada. O sistema
impede criar bloqueio fora dela — trava dura para a IA, override com aviso para Fernando.
Ver termo em `CONTEXT.md`.

## Decisões

- **Regra composta numa única tabela** `barravips.modelo_disponibilidade`
  `(modelo_id, data_inicio, data_fim NULL-able, dia_semana 0..6, hora_inicio, hora_fim)`.
  A disponibilidade efetiva é a **união** das regras; um instante é reservável se alguma
  regra o cobre. Modelo sem regra = reservável sempre (preserva o fluxo atual).
- **Datas absolutas, múltiplas** (não recorrência por dia-do-mês). `data_fim` NULL = período
  aberto/indefinido. Ciclo mensal fixo vira o operador recadastrar a cada ciclo.
- **Janela horária por dia da semana**, podendo cruzar a meia-noite (`hora_fim <= hora_inicio`).
  A janela pertence ao dia da semana do seu **início** e transborda para o dia civil seguinte
  (sex 18:00–04:00 cobre sex 18:00 até sáb 04:00) — por isso **não** há CHECK `hora_inicio < hora_fim`.
- **Valida-se apenas o INÍCIO do bloqueio** contra a janela (data ∈ período ∧ dia-da-semana ∧
  hora ∈ janela). O fim pode estender além: Pernoite dura 12h (`decisao_duracao_auto_atendimento`)
  e estouraria qualquer janela menor se o intervalo inteiro fosse exigido.
- **Folga/fora-do-período não é materializada como bloqueio.** `data_fim` aberta não tem fim
  finito para virar linha, e gerar bloqueios para todo dia de folga seria sujo. É uma config
  separada que a leitura da agenda subtrai. (A EXCLUDE constraint dos bloqueios cobre só
  `bloqueado`/`em_atendimento` e não serve para isso.)
- **Trava dura para a IA, override para Fernando.** A IA nunca cria nem sugere fora da
  disponibilidade. Fernando vê aviso no painel e pode forçar (`confirmar_fora_disponibilidade`),
  mesmo padrão do `confirmar` ao cancelar bloqueio `em_atendimento`.
- **Persona fora-do-período revela e ancora.** Diferente do bloqueio (onde a IA mente com
  desculpa pessoal para preservar exclusividade), fora-do-período não há outro cliente a
  esconder: a IA assume que está fora, informa quando volta e oferece a 1ª data disponível.
- **Salvar disponibilidade que deixa bloqueios futuros fora dela** salva normalmente e emite
  alerta não-bloqueante; nunca deleta nem cancela bloqueio automaticamente.

## Considered Options

- **Duas camadas separadas** (tabela de períodos + template semanal): mais limpo
  conceitualmente, mas dobra tabelas, telas e validações e adiciona a interseção entre elas.
  Rejeitado — a regra composta única cobre datas+dias+horas com menos superfície.
- **Validar o intervalo inteiro do bloqueio**: correto para atendimentos curtos, mas
  inviabiliza Pernoite (12h) em qualquer janela menor. Rejeitado.
- **Trava dura também para Fernando** (lê o texto da reunião ao pé da letra): rejeitado por
  ergonomia — exceção pontual não deve exigir editar o período; o aviso + override resolve.

## Consequences

- O horário de operação global (`settings.operacao_hora_*`) permanece sendo apenas
  quiet-hours do **Reengajamento**, ortogonal à Disponibilidade (horas reserváveis por modelo).
- A validação `modelo_disponivel_em(...)` precisa ser um helper reutilizável: hoje a chama
  `POST/PATCH /bloqueios`; no M3f a tool de escrita da IA (`criar_bloqueio_previo`) reusa.
- A IA recebe as regras (compactas) no contexto dinâmico do turno — fora do prefixo cacheado,
  renderizadas em ordem determinística para não invalidar o cache.
