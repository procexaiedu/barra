"""Le o export do WhatsApp do Grupo financeiro (`_chat.txt` + anexos) como mensagens do modulo.

O export e a UNICA fonte de verdade do comportamento deste agente (spec 0005, "Further Notes"):
o que ele tem que aguentar e a grafia real do grupo, com as quebras de linha, os acentos, os
apelidos e os anexos que a operacao produziu de verdade.

Formato do export do iOS (o que a Elite Baby usa):

    [06/08/2026, 10:25:46] ~ Parcerias: Site
    ‎[13/08/2026, 16:41:12] ~ Parcerias: ‎<anexado: 00002999-PHOTO-....jpg>

Tres particularidades que mordem, e por isso este parser nao e um `split(":")`:

* **Mensagem de varias linhas.** O anuncio de venda — o dado mais importante do grupo — SEMPRE
  tem quebra de linha ("Atendimento no nosso local\\nCliente Gabriel\\n..."). Linha que nao comeca
  com `[data, hora]` e continuacao da anterior.
* **Marcas invisiveis.** O WhatsApp intercala U+200E (LRM) antes do colchete e antes do anexo.
  Sem tira-las, `startswith("[")` falha e toda mensagem com anexo vira continuacao da anterior.
* **Linhas de sistema.** "criou este grupo", "adicionou voce", o aviso de criptografia: elas tem a
  forma de mensagem e nao sao mensagem de ninguem. Ficam marcadas como `sistema` para o replay
  poder pula-las sem que elas sumam da contagem.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from barra.dominio.grupo_financeiro.modelos import (
    AudioDoGrupo,
    ImagemDoGrupo,
    MensagemDoGrupo,
    TipoMensagem,
)

_INVISIVEIS = dict.fromkeys(map(ord, "‎‏‪‬⁦⁩"), None)
"""LRM/RLM e os isolados direcionais que o WhatsApp injeta em volta de numeros e anexos."""

_ESPACOS = {0x202F: " ", 0x00A0: " ", 0x2011: "-"}
"""O WhatsApp escreve o AUTOR com espacos que nao sao o espaco: `~<U+202F>Parcerias`
(narrow no-break space) e `+55<U+00A0>11<U+00A0>96854<U+2011>4493` (no-break space +
non-breaking hyphen). Os codepoints vao escritos assim, e nao colados, porque o alerta de
caractere ambiguo do ruff nao distingue o exemplo do defeito.

Isso nao e cosmetico: o autor e a IDENTIDADE da mensagem no replay — e o que separa "a gestora
postou a venda" de "a modelo ditou a propria chave Pix" (ticket 12). Com o U+202F intacto,
`"~ Parcerias" in roteiro.gestoras` da False para TODA gestora, o replay carimba o numero da
modelo em todas as mensagens do grupo e a tranca de autoria e medida ao contrario — verde por um
motivo que a producao nao tem. Vira espaco de verdade (e nao apagado) porque o roteiro escreve
`~ Dani` com espaco comum."""

_CABECALHO = re.compile(
    r"^\[(?P<dia>\d{2})/(?P<mes>\d{2})/(?P<ano>\d{4}),\s(?P<hora>\d{2}):(?P<min>\d{2}):(?P<seg>\d{2})\]\s(?P<autor>.+?):\s?(?P<texto>.*)$"
)
_ANEXO = re.compile(r"<anexado:\s*(?P<arquivo>[^>]+)>")
_RESPONDE = re.compile(r"^\[\[responde:(?P<indice>\d+)\]\]\s*")

_MARCAS_DE_SISTEMA = (
    "criou este grupo",
    "adicionou você",
    "As mensagens e ligações são protegidas",
    "saiu do grupo",
    "mudou o nome do grupo",
    "alterou a descrição do grupo",
)

TipoDoAnexo = Literal["texto", "imagem", "audio", "outro"]
"""O que a linha do export CARREGA. `outro` (sticker, video) nao tem tipo na porta e entra como
`texto` vazio — a mensagem existe no log e nao diz nada, que e o que ela e."""

BRT = timedelta(hours=-3)
"""O grupo escreve no relogio de Brasilia; o modulo trabalha em UTC (a data da venda sai de
`dia_brt`). Converter aqui, e nao la, mantem o replay com a MESMA aritmetica da producao."""


@dataclass(frozen=True)
class LinhaDoExport:
    """Uma mensagem do export, ja normalizada — o insumo do replay."""

    indice: int
    quando: datetime
    """Em UTC, convertido do horario de Brasilia do export."""
    autor: str
    texto: str
    anexo: str | None = None
    """Nome do arquivo no zip (`00002999-PHOTO-....jpg`), quando a mensagem era midia."""
    sistema: bool = False
    apagada: bool = False
    """A linha "Mensagem apagada": o WhatsApp nao diz QUAL mensagem morreu, so que houve uma."""
    responde: int | None = None
    """Indice da mensagem citada — so nos exports SINTETICOS (`[[responde:6]]` na primeira linha).

    O export do WhatsApp **nao exporta citacao**: a resposta sai como mensagem solta, e por isso o
    export real nunca exercita a correcao por quote (ticket 05), que e a escrita mais perigosa do
    modulo — ela sobrescreve dinheiro ja registrado. O marcador existe para o roteiro sintetico
    poder dizer o que o formato do WhatsApp perdeu, e nada mais: numa linha de export real ele
    nunca aparece."""

    @property
    def vazia(self) -> bool:
        """Cabecalho sem corpo: `[13/08/2026, 17:55:10] ~ FEH SANTOS:` e nada depois.

        O export do iOS escreve isso quando a mensagem nao pode ser exportada (mídia expirada,
        aviso de participante). Nao e mensagem: em producao nada disso chega ao webhook, e deixar
        passar gasta um turno do agente com corpo vazio — dois "nao_e_anuncio" fantasmas no fim do
        export da Yasmin, que contam como comportamento medido sem ter sido nada.
        """
        return not self.texto and self.anexo is None and not self.sistema and not self.apagada

    @property
    def tipo(self) -> TipoDoAnexo:
        """`texto` | `imagem` | `audio` | `outro` — o que a porta precisa saber da midia."""
        if self.anexo is None:
            return "texto"
        nome = self.anexo.upper()
        if "PHOTO" in nome or nome.endswith((".JPG", ".JPEG", ".PNG", ".WEBP")):
            return "imagem" if "STICKER" not in nome else "outro"
        if "AUDIO" in nome or "PTT" in nome or nome.endswith((".OPUS", ".OGG", ".MP3", ".M4A")):
            return "audio"
        return "outro"


def ler_export(caminho: Path) -> list[LinhaDoExport]:
    """Le `_chat.txt` inteiro. Mensagem de varias linhas vira UMA `LinhaDoExport`."""
    bruto = caminho.read_text(encoding="utf-8")
    linhas: list[LinhaDoExport] = []
    pendente: list[str] = []

    def fechar() -> None:
        if not pendente or not linhas:
            return
        anterior = linhas[-1]
        linhas[-1] = LinhaDoExport(
            indice=anterior.indice,
            quando=anterior.quando,
            autor=anterior.autor,
            texto="\n".join([anterior.texto, *pendente]).strip("\n"),
            anexo=anterior.anexo,
            sistema=anterior.sistema,
            apagada=anterior.apagada,
            responde=anterior.responde,
        )
        pendente.clear()

    for crua in bruto.splitlines():
        limpa = crua.translate(_INVISIVEIS).translate(_ESPACOS)
        achado = _CABECALHO.match(limpa)
        if achado is None:
            if limpa.strip():
                pendente.append(limpa)
            continue

        fechar()
        texto = achado["texto"].strip()
        citacao = _RESPONDE.match(texto)
        if citacao is not None:
            texto = texto[citacao.end() :].strip()
        anexo = _ANEXO.search(texto)
        quando = (
            datetime(
                int(achado["ano"]),
                int(achado["mes"]),
                int(achado["dia"]),
                int(achado["hora"]),
                int(achado["min"]),
                int(achado["seg"]),
                tzinfo=UTC,
            )
            - BRT
        )
        linhas.append(
            LinhaDoExport(
                indice=len(linhas) + 1,
                quando=quando,
                autor=achado["autor"].strip(),
                texto="" if anexo else texto,
                anexo=anexo["arquivo"].strip() if anexo else None,
                sistema=any(marca in texto for marca in _MARCAS_DE_SISTEMA),
                apagada=texto.strip() == "Mensagem apagada",
                responde=int(citacao["indice"]) if citacao else None,
            )
        )

    fechar()
    return linhas


# --- do export para a porta ---------------------------------------------------------------------
#
# A traducao "linha do export -> `MensagemDoGrupo`" mora AQUI, e nao no replay, desde que o
# backfill (ticket 03) passou a ser o segundo chamador. Dois construtores de mensagem seriam duas
# identidades para a mesma linha do mesmo grupo — e identidade e o que a idempotencia do modulo usa
# para decidir se ja viu esta mensagem (`chave_dedup`). Divergir aqui e importar o mesmo export
# duas vezes sem que nada colida.

_MIMETYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}

JID_DO_HISTORICO = "historico@backfill.invalid"
"""O autor de quem NAO e a modelo, quando a mensagem vem de um export.

O export do WhatsApp nao exporta o telefone de quem postou — so o nome de exibicao ("~ Parcerias").
Inventar um telefone plausivel aqui nao seria cosmetico: `vendedores.whatsapp_jid` e o resolver
closed-world do telefonista (ADR-0048), e ele casa o JID **literalmente**. Um numero de fantasia
que por acaso esteja cadastrado atribuiria comissao retroativa a um telefonista que nao vendeu
nada em agosto — a comissao que a spec 0006 diz, com todas as letras, que o backfill NAO retroage.

O dominio `.invalid` e reservado por RFC 2606 e nao tem a forma de nenhum JID do WhatsApp
(`@s.whatsapp.net`, `@lid`, `@g.us`), entao ele nao pode casar com cadastro nenhum nem por
acidente nem por normalizacao. E, sem digitos, `autor_e_a_modelo` devolve False por construcao —
que e a resposta certa: quem posta pelo export nao e a dona do grupo, a menos que o roteiro diga
que aquele numero e o dela."""


def apelido_do_export(caminho: Path) -> str:
    """Um nome curto e estavel para o export — o NAMESPACE dos ids sinteticos.

    So `[a-z0-9-]`, derivado do nome do arquivo/pasta. Existe porque o export nao traz o
    `evolution_message_id` de nada (o WhatsApp nao exporta id), e o replay precisa inventar um: o
    indice da linha. Indice **sozinho** e global — a mensagem 1 do grupo da Yasmin e a mensagem 1
    do grupo da Julia produzem a mesma `chave_dedup` (`evo:...0001`), e `chave_dedup` tem indice
    UNICO na tabela inteira, nao por grupo. Nos oito exports do backfill, isso significaria o
    segundo grupo inteiro entrando como "entrega duplicada" e sumindo em silencio.
    """
    bruto = caminho.stem if caminho.suffix else caminho.name
    limpo = re.sub(r"[^a-z0-9]+", "-", bruto.lower()).strip("-")
    return limpo or "export"


def id_da_mensagem(apelido: str, indice: int) -> str:
    """O `evolution_message_id` sintetico de uma linha do export. Deterministico de proposito.

    Deterministico E a idempotencia do backfill (user story 53): rodar de novo depois de corrigir
    um bug produz exatamente as mesmas chaves, `registrar_mensagem` bate no `ON CONFLICT` e a
    porta para na primeira linha de cada mensagem ja importada — sem duplicar venda, comprovante
    nem cobranca.
    """
    return f"{apelido}:{indice:05d}"


def mensagem_do_export(
    linha: LinhaDoExport,
    *,
    grupo_jid: str,
    gestoras: Sequence[str],
    numero_da_modelo: str | None,
    anexos: Mapping[str, bytes],
    apelido: str,
) -> MensagemDoGrupo:
    """A linha do export como a porta unica a recebe — a MESMA traducao no replay e no backfill.

    `gestoras` sao os nomes de exibicao de quem NAO e a dona do grupo; todo o resto do export e
    ela, e por isso `numero_da_modelo` tem que ser o numero que o `_chat.txt` mostra (e o que
    separa "a modelo ditou a chave dela" de "um gestor ditou a chave da casa"). Sem numero
    cadastrado, TODA mensagem cai como de terceiro — o lado seguro.

    Os bytes do anexo viajam junto (`ImagemDoGrupo`/`AudioDoGrupo`) exatamente como o webhook os
    entrega ao vivo: e o que faz o comprovante do zip passar pelo mesmo OCR da producao.
    """
    de_gestora = linha.autor in gestoras
    conteudo = anexos.get(linha.anexo) if linha.anexo else None
    mimetype = _MIMETYPES.get(Path(linha.anexo).suffix.lower()) if linha.anexo else None
    bruto = linha.tipo
    tipo: TipoMensagem = bruto if bruto in ("texto", "imagem", "audio") else "texto"
    return MensagemDoGrupo(
        grupo_jid=grupo_jid,
        texto=linha.texto,
        tipo=tipo,
        imagem=(ImagemDoGrupo(conteudo, mimetype) if tipo == "imagem" and conteudo else None),
        audio=(AudioDoGrupo(conteudo, mimetype) if tipo == "audio" and conteudo else None),
        evolution_message_id=id_da_mensagem(apelido, linha.indice),
        quoted_message_id=(
            id_da_mensagem(apelido, linha.responde) if linha.responde is not None else None
        ),
        autor_nome=linha.autor.lstrip("~ ").strip(),
        autor_jid=(
            JID_DO_HISTORICO
            if de_gestora or not numero_da_modelo
            else f"{numero_da_modelo}@s.whatsapp.net"
        ),
        recebida_em=linha.quando,
    )
