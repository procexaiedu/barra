-- 0009: Adiciona categoria aos programas para agrupar variantes por tipo
-- Exemplo: categoria="Atendimento ao casal", nome="1 hora" / "2 horas" / "Pernoite"

ALTER TABLE barravips.programas ADD COLUMN categoria text;

-- Seed: categorias para os programas padrão (sem categoria = standalone)
-- Atualiza seed existente com categoria nula (padrão)
-- Novos programas de exemplo para demonstrar o agrupamento:

INSERT INTO barravips.programas (nome, duracao_horas, descricao, categoria) VALUES
  ('1 hora',    1.00, NULL, 'Atendimento ao casal'),
  ('2 horas',   2.00, NULL, 'Atendimento ao casal'),
  ('Pernoite', 12.00, NULL, 'Atendimento ao casal');
