-- Adiciona 'cartao' às formas de pagamento aceitas (pix, dinheiro, outro, cartao).
-- O painel já oferecia a opção "Cartão", mas o enum não a continha — gravar dava 500
-- (invalid input value for enum). Valor sem acento, alinhado a 'pix'/'dinheiro'/'outro'.
ALTER TYPE barravips.forma_pagamento_enum ADD VALUE IF NOT EXISTS 'cartao';
