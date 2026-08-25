"""Gera os comprovantes SINTETICOS que os exports de replay postam no grupo.

Rodar com o Python do sistema (Pillow nao esta no ambiente da API):

    python3 evals/grupo_financeiro/exports/gerar_comprovantes.py

Dado ficticio de ponta a ponta — nome, CPF, chave. O motivo e o mesmo das fixtures dos testes
(`tests/fixtures/grupo_financeiro/README.md`): comprovante real carrega PII de terceiro, e
commitar um arquivo e publica-lo no historico do git para sempre.

Diferente das fixtures, estas imagens sao LIDAS DE VERDADE quando o replay roda com `--ocr` — sao
elas que provam que o OCR le um comprovante inteiro, e nao so que os bytes atravessam a porta.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

AQUI = Path(__file__).resolve().parent

# (pasta do export, arquivo, valor, data, chave de destino, titular, pagador)
COMPROVANTES = [
    (
        "fechamento_parcial_e_sobra",
        "COMP-2026-08-05-1200.jpg",
        "R$ 1.200,00",
        "05/08/2026",
        "a7c3e910-2222-4d66-8bb1-90c4d1f75555",
        "TITULAR DA CASA",
        "SABRINA DE SOUZA LIMA",
    ),
    (
        "fechamento_parcial_e_sobra",
        "COMP-2026-08-06-1000.jpg",
        "R$ 1.000,00",
        "06/08/2026",
        "a7c3e910-2222-4d66-8bb1-90c4d1f75555",
        "TITULAR DA CASA",
        "SABRINA DE SOUZA LIMA",
    ),
    (
        "fechamento_parcial_e_sobra",
        "COMP-2026-08-07-385.jpg",
        "R$ 385,80",
        "07/08/2026",
        "+55 71 99984 0879",
        "AGENCIA DE ANUNCIOS LTDA",
        "SABRINA DE SOUZA LIMA",
    ),
    # O comprovante que cabe nos DOIS eixos: R$ 600 e ao mesmo tempo a venda em pix do Alex e a
    # cobranca do portal. Vai para a chave da casa justamente para tirar do caminho a saida facil
    # ("chave da agencia => cobranca") — o que se mede aqui e a recusa a chutar.
    (
        "cobranca_gemea_e_comprovante",
        "COMP-2026-08-18-600.jpg",
        "R$ 600,00",
        "18/08/2026",
        "b91d7e02-4444-4f88-8ad3-21c6b0554477",
        "TITULAR DA CASA",
        "NICOLE FERRAZ DA SILVA",
    ),
    # Fechamento para uma chave que a casa NAO conhece: o abate acontece (o valor fecha a venda),
    # e o ⚠️ tem que sair junto — e a user story 11.
    # A prova da cobranca SEMANAL: a mesma imagem volta na semana seguinte, quando ja existe uma
    # segunda cobranca do mesmo valor. E o unico comprovante do conjunto que e enviado duas vezes
    # de proposito, e o que ele mede e o dedup por foto no eixo da cobranca.
    (
        "renovacao_da_cobranca",
        "COMP-2026-08-18-385.jpg",
        "R$ 385,80",
        "18/08/2026",
        "+55 71 99984 0879",
        "AGENCIA DE ANUNCIOS LTDA",
        "PAULA MARTINS ROCHA",
    ),
    (
        "cobranca_gemea_e_comprovante",
        "COMP-2026-08-19-900.jpg",
        "R$ 900,00",
        "19/08/2026",
        "joao.pereira.87@gmail.com",
        "JOAO PEREIRA DOS SANTOS",
        "NICOLE FERRAZ DA SILVA",
    ),
]


def _fonte(tamanho: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for caminho in ("/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"):
        if Path(caminho).exists():
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default()


def gerar(destino: Path, valor: str, data: str, chave: str, titular: str, pagador: str) -> None:
    img = Image.new("RGB", (720, 1100), (245, 247, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([(0, 0), (720, 130)], fill=(20, 40, 90))
    d.text((40, 55), "BANCO FICTICIO S/A", font=_fonte(22), fill=(255, 255, 255))

    linhas = [
        (200, "COMPROVANTE DE TRANSFERENCIA PIX", 26),
        (270, f"Valor: {valor}", 34),
        (340, f"Data: {data}", 22),
        (430, f"Pagador: {pagador}", 22),
        (470, "CPF: ***.000.000-**", 20),
        (560, f"Recebedor: {titular}", 22),
        (600, f"Chave Pix: {chave}", 20),
        (700, "Numero de controle: 000000000000000000", 18),
        (820, "FIXTURE SINTETICA - dado ficticio, nao e comprovante real", 18),
    ]
    for y, texto, tamanho in linhas:
        d.text((40, y), texto, font=_fonte(tamanho), fill=(15, 20, 30))

    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino, "JPEG", quality=88)


def main() -> None:
    for pasta, arquivo, valor, data, chave, titular, pagador in COMPROVANTES:
        caminho = AQUI / pasta / arquivo
        gerar(caminho, valor, data, chave, titular, pagador)
        print(f"{caminho.relative_to(AQUI)}  ({caminho.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
