-- Comprovante de ENTRADA da modelo: o Pix que aponta para o lado contrario.
--
-- Do export real do Grupo financeiro da Yasmin (06/08/2026): a gestora postou no grupo o
-- comprovante de R$ 658,07 que a CLIENTE fez PARA a modelo. Ate aqui o agente lia esse
-- comprovante como transferencia dela — perguntava "é de quê?", disparava o alarme de "chave fora
-- da lista da casa" apontando o nome da propria modelo e, se houvesse venda em pix aberta na
-- fila, teria ABATIDO: dinheiro que a casa nao recebeu virando venda comprovada.
--
-- A quinta classe existe para esse comprovante ficar guardado (ele e prova de que a venda foi
-- paga) sem entrar no eixo do fechamento, que mede o que saiu da mao dela para a casa. Ele nao
-- abate venda, nao quita cobranca e nao gera pergunta.
--
-- Sem `valor IS NOT NULL` no CHECK dedicado: entrada sem valor legivel nao chega aqui (a leitura
-- ilegivel morre antes, em `ilegivel`), mas amarrar a constraint tambem a essa classe custaria
-- uma migration nova no dia em que a conduta mudar.

ALTER TABLE barravips.comprovantes_do_grupo
  DROP CONSTRAINT IF EXISTS comprovantes_do_grupo_classificacao_valida;

ALTER TABLE barravips.comprovantes_do_grupo
  ADD CONSTRAINT comprovantes_do_grupo_classificacao_valida
    CHECK (classificacao IN
      ('fechamento', 'cobranca', 'entrada_da_modelo', 'nao_classificado', 'ilegivel'));

COMMENT ON COLUMN barravips.comprovantes_do_grupo.classificacao IS
  'fechamento (abateu venda pix aberta) | cobranca (quitou uma Cobranca da agencia — abate a '
  'cobranca, NUNCA as vendas, ticket 08) | entrada_da_modelo (o cliente pagou A modelo: fica de '
  'prova, nao abate nada) | nao_classificado (nao casou com nada, ou casaria com as duas coisas: '
  'pergunta no grupo e fica retido) | ilegivel (OCR nao leu; o agente pediu reenvio).';
