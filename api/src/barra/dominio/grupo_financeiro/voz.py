"""A voz do Agente financeiro: como reconhecer o que SAIU dele (spec 0005).

Existe por uma razao so, e ela e defensiva. O corte de eco da porta e o `de_mim` do envelope
(`fromMe`), e `fromMe` e ambiguo nesta casa desde sempre (`webhook/CLAUDE.md`): ele e relativo a
INSTANCIA que entregou o evento, e o Grupo financeiro tem a modelo dentro — o WhatsApp dela e
outra instancia apontando para o mesmo webhook. Quando a entrega que vence e a dela, o `fromMe`
se INVERTE: as falas da modelo chegam como se fossem do agente, e o recibo do agente chega como se
fosse de gente.

O filtro de instancia do webhook (`_e_a_instancia_da_procex`) fecha essa porta — mas ele e
fail-OPEN quando `GRUPO_FINANCEIRO_INSTANCIA` nao esta configurada, que e exatamente o estado de
um ambiente recem-subido. E o recibo do agente tem, por design, a gramatica de um anuncio de venda
("✅ Registrei: Yasmin R$ 700,00 · 08/08 · Cliente Gabriel"): sem esta segunda tranca, o agente
mal configurado se auto-registraria, e o dedup por conteudo esconderia o sintoma (a segunda linha
nao entra, entao ninguem ve nada errado) ate o dia em que o recibo falasse de duas modelos.

**Reconhecimento por PREFIXO LITERAL, nao por emoji solto.** "✅" sozinho e uma mensagem que um
humano manda ("✅" como "ok"); "✅ Registrei:" nao e. A lista abaixo e fechada e o teste
`test_voz_do_agente` varre as falas reais do modulo para garantir que ela nao envelhece — fala
nova sem prefixo aqui quebra o teste, nao a producao.
"""

from __future__ import annotations

PREFIXOS_DO_AGENTE = (
    "✅ Registrei:",
    "✅ Anotei:",
    "✅ Comprovante conferido:",
    "✅ Tudo conciliado",
    "🧾 Registrei a cobrança:",
    "♻️ Essa já estava registrada:",
    "♻️ Essa cobrança já estava registrada:",
    "♻️ Esse comprovante eu já tinha conferido",
    "♻️ Não apliquei:",
    "❓ ",
    "📊 Fechamento",
    "📷 Não consegui ler",
    "⚠️ Esse Pix",
    "☀️ Bom dia!",
)
"""Todo comeco de fala que so o agente escreve. Cobrir a PRIMEIRA linha basta: as falas
multi-linha (fechamento, cobranca da manha) sempre abrem por um destes."""


def e_fala_do_agente(texto: str) -> bool:
    """Este texto saiu do proprio agente? Usado como segunda tranca do corte de eco.

    Uma mensagem HUMANA que comece assim tambem e ignorada — e isso e o certo: alguem colando o
    recibo de volta no grupo nao esta anunciando uma venda nova. Quem quer corrigir responde
    CITANDO o recibo, e a correcao por quote nao passa por aqui (ela le o texto do humano, que nao
    comeca com o prefixo).
    """
    primeira = texto.lstrip().split("\n", 1)[0]
    return any(primeira.startswith(prefixo) for prefixo in PREFIXOS_DO_AGENTE)
