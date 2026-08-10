# Detector de empurrão na cotação (rubrica do juiz ponto 2, só 2 features)

Você recebe TURNOS de cotação gerados (a fala em que a vendedora passa o PREÇO ao cliente).
Para cada turno, detecte SÓ estes dois traços booleanos, EXATAMENTE como na rubrica §12:

- f_glued_urgency — pressa/urgência COLADA ao número no mesmo turno da cotação:
  "vamos confirmar agora?", "seria agora?", "vem agora", "fechamos já?", "garante seu horário",
  pressão temporal grudada ao preço. (Sondar "seria hoje?" ANTES de ter passado preço não conta;
  o que conta é urgência no MESMO turno em que o valor é dado.)
- f_glued_question — pergunta/CTA DE FECHAMENTO colada ao preço no mesmo turno da cotação:
  "vamos fechar?", "posso confirmar?", "te espero então?", "bora?", "qual horário fechamos?".
  (Uma pergunta de QUALIFICAÇÃO leve — "seria pra hoje amor?" sem ser CTA de fechamento — é borda;
  marque f_glued_question só quando há empurrão claro de fechar/confirmar grudado no valor.)

REGRAS:
- Avalie SÓ o turno da cotação fornecido (a fala da vendedora com o preço). Nada de inferir reação do cliente.
- Se o turno NÃO contém um preço/valor (a candidata não cotou), marque sem_cotacao=true e os dois flags=false.
- Seja conservador e consistente com a rubrica do juiz: o empurrão é urgência/CTA GRUDADA ao número.
