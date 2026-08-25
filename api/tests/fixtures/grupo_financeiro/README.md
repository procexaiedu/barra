# Fixtures do Grupo financeiro (spec 0005, ticket 07)

Dois **Comprovantes de transferência** SINTÉTICOS, usados pelos testes de OCR da porta única:

| arquivo | o que ele representa |
|---|---|
| `comprovante_1200_fechamento.jpg` | R$ 1.200,00 · 12/08/2026 · destino = a chave de fechamento da casa. Fecha as duas vendas de R$ 600,00 conferidas no roteiro do ticket 09. |
| `comprovante_385_80_cobranca_3rj.jpg` | R$ 385,80 · 13/08/2026 · destino = a agência. Pagamento da **Cobrança da agência**; aqui serve de caso "não casa com venda nenhuma", que o ticket 08 reclassifica. |

**O OCR nunca roda nos testes.** Nenhum teste desta casa pode exigir chave de provider: o leitor é
stubado e devolve a leitura que o roteiro do teste precisa. Os bytes das imagens entram assim mesmo
porque é por eles que passam o transporte da porta, a detecção de mime por magic bytes
(`core/vision.detectar_mime_imagem` — os arquivos começam com `FF D8 FF`) e a contagem de quantas
vezes o agente pagaria OCR — as três coisas que um `b"fake"` não exercita. O CONTEÚDO da imagem é
irrelevante para o teste, e é por isso que ele pode ser (e é) fictício.

**Por que sintéticas e não os comprovantes reais do export.** As duas imagens já foram, num
primeiro corte, as fotos reais do export "WhatsApp Chat - Modelo Yasmin Ruiva/ financeiro 🤑":
carregavam nome civil da modelo, nome civil do titular de destino, CPFs mascarados pelo banco,
CNPJ, chave Pix viva e número de controle da transação. Nada disso é credencial, mas é PII de
pessoa real — e commitar um arquivo é publicá-lo no histórico do git para sempre. Fixture com dado
real de terceiro não entra no repo; se algum dia um teste precisar do pixel exato de um comprovante
real, ele lê de um caminho fora do repo, por env var, e é `skip` quando o arquivo não existe.

Regenerar (Pillow, determinístico): ver o bloco de geração no cabeçalho deste README no histórico
da consolidação do módulo — qualquer JPEG com os mesmos magic bytes e ordem de grandeza de tamanho
(dezenas de KB) serve.
