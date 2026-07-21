"""Auto-fechamento por comprovante de Pix no grupo de Coordenacao (auto-baixa).

Feature: a modelo responde o card de fechamento (ou poe #N na legenda) com a FOTO do comprovante
de Pix; o sistema faz OCR do valor e fecha o atendimento (mesmo caminho do `fechado [valor]`).

Cobre:
- Roteamento no webhook (`_processar_comprovante_grupo`): ancora por quote ou #N na legenda;
  "valor digitado vence" (legenda com comando completo NAO chama OCR); "#5" na legenda e ANCORA,
  nunca valor R$5; sem ancora e sem midia -> recuperacao, sem enfileirar.
- Worker (`fechar_via_comprovante`): fecha pela porta unica com valor lido + forma_pagamento=pix;
  atendimento ja finalizado -> no-op (dedup); sem valor legivel -> pede valor por texto.
- Parser (`_quoted_id`): le o quote de uma IMAGEM (imageMessage.contextInfo), nao so de texto.
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from barra.webhook import routes
from barra.webhook.parser import MensagemEvolution, extrair_mensagem
from barra.workers import comprovante_fechamento as cf
from barra.workers.pix import ExtracaoPix

_MODELO = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_ATEND = UUID("a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1")
_CONVERSA = UUID("c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1")
_NUMERO = 5


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class FakeConn:
    """Resolve modelo por instance e atendimento por (numero, modelo) — mesmo estilo do SEC-02."""

    def __init__(self, estado: str = "Em_execucao") -> None:
        self.binds: list[tuple[str, Any]] = []
        self._estado = estado

    async def execute(self, query: str, params: Any = None) -> _Result:
        self.binds.append((query, params))
        if "FROM barravips.envios_evolution WHERE evolution_message_id" in query:
            return _Result([])
        if "SELECT id FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"id": _MODELO}])
        if "FROM barravips.atendimentos" in query and "numero_curto = %s" in query:
            numero, modelo_id = params[0], params[1]
            # Espelha o gate `estado NOT IN ('Fechado','Perdido')` da query real.
            if (numero, modelo_id) == (_NUMERO, _MODELO) and self._estado not in (
                "Fechado",
                "Perdido",
            ):
                return _Result([{"id": _ATEND}])
            return _Result([])
        return _Result([])


class FakeArq:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, name: str, **kw: Any) -> None:
        self.jobs.append((name, kw))


class FakeMinio:
    def __init__(self) -> None:
        self.puts: list[tuple[str, str]] = []

    def put_object(
        self, bucket: str, key: str, data: Any, length: int, content_type: str | None = None
    ) -> None:
        self.puts.append((bucket, key))


def _request(minio: Any, arq: Any) -> Any:
    settings = SimpleNamespace(
        evolution_fernando_jids=[], minio_bucket_media="media", lembrete_valor_tolerancia_min=15
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings, minio=minio, arq=arq))
    )


def _img(
    *, caption: str | None = None, quoted: str | None = None, instance: str = "inst-a"
) -> MensagemEvolution:
    return MensagemEvolution(
        evolution_message_id="IMG-1",
        instance_id=instance,
        remote_jid="120363000000000000@g.us",
        sender_jid=None,
        from_me=True,
        texto="",
        tipo="imagem",
        media_url=None,
        quoted_message_id=quoted,
        caption=caption,
    )


# --- Roteamento no webhook -----------------------------------------------------------------------


async def test_quote_enfileira_ocr(monkeypatch) -> None:
    """Foto respondendo o card (quoted_numero resolvido) -> sobe ao MinIO e enfileira o worker."""
    minio, arq, conn = FakeMinio(), FakeArq(), FakeConn()
    res = await routes._processar_comprovante_grupo(
        conn, _request(minio, arq), _img(), (b"\xff\xd8\xffimg", "image/jpeg"), "modelo", _NUMERO
    )
    assert res == {"status": "comprovante_enfileirado"}
    assert len(minio.puts) == 1
    assert minio.puts[0][1].startswith(f"comprovantes_fechamento/{_ATEND}/")
    assert arq.jobs == [
        (
            "fechar_via_comprovante",
            {
                "atendimento_id": str(_ATEND),
                "object_key": minio.puts[0][1],
                "evolution_message_id": "IMG-1",
                "_job_id": "fechar_comprovante:IMG-1",
            },
        )
    ]


async def test_numero_na_legenda_enfileira(monkeypatch) -> None:
    """Sem quote, mas #N na legenda -> resolve e enfileira."""
    minio, arq = FakeMinio(), FakeArq()
    res = await routes._processar_comprovante_grupo(
        FakeConn(),
        _request(minio, arq),
        _img(caption=f"#{_NUMERO}"),
        (b"\xff\xd8\xffimg", "image/jpeg"),
        "modelo",
        None,
    )
    assert res == {"status": "comprovante_enfileirado"}
    assert arq.jobs and arq.jobs[0][1]["atendimento_id"] == str(_ATEND)


async def test_legenda_hash_e_ancora_nao_valor(monkeypatch) -> None:
    """EDGE: '#5' na legenda e ANCORA (#N=5), nunca o valor R$5 (nao aciona o caminho de fechar
    por valor). Vai pro OCR, que le o valor real do comprovante."""
    aplicados: list[Any] = []

    async def _fake_aplicar(*a: Any, **k: Any) -> None:
        aplicados.append(k.get("comando"))

    monkeypatch.setattr(routes, "aplicar_comando", _fake_aplicar)
    minio, arq = FakeMinio(), FakeArq()
    res = await routes._processar_comprovante_grupo(
        FakeConn(),
        _request(minio, arq),
        _img(caption=f"#{_NUMERO}"),
        (b"\xff\xd8\xffimg", "image/jpeg"),
        "modelo",
        _NUMERO,
    )
    # OCR enfileirado, nenhum fechamento sincrono por "valor pelado".
    assert res == {"status": "comprovante_enfileirado"}
    assert aplicados == []


async def test_valor_digitado_vence(monkeypatch) -> None:
    """Legenda com comando COMPLETO (`fechado 1500`) fecha pelo valor digitado, SEM OCR."""
    aplicados: list[dict[str, Any]] = []

    async def _fake_aplicar(conn: Any, **k: Any) -> None:
        aplicados.append(k)

    async def _fake_responder(*a: Any, **k: Any) -> None:
        pass

    monkeypatch.setattr(routes, "aplicar_comando", _fake_aplicar)
    monkeypatch.setattr(routes, "_responder_grupo", _fake_responder)
    minio, arq = FakeMinio(), FakeArq()
    res = await routes._processar_comprovante_grupo(
        FakeConn(),
        _request(minio, arq),
        _img(caption="fechado 1500"),
        (b"\xff\xd8\xffimg", "image/jpeg"),
        "modelo",
        _NUMERO,
    )
    assert res == {"status": "processed"}
    assert arq.jobs == []  # OCR nao acionado
    assert len(aplicados) == 1
    assert aplicados[0]["comando"] == "registrar_fechado"
    assert aplicados[0]["payload"]["valor_final"] == Decimal("1500")


async def test_ia_pausa_na_legenda_nao_aciona_ocr(monkeypatch) -> None:
    """Paridade com `IA assume`/`fechado`: legenda com comando COMPLETO (`IA pausa #N`) pausa a
    IA direto, SEM cair no OCR de comprovante (mesma disciplina do 'valor digitado vence')."""
    aplicados: list[dict[str, Any]] = []

    async def _fake_aplicar(conn: Any, **k: Any) -> None:
        aplicados.append(k)

    async def _fake_responder(*a: Any, **k: Any) -> None:
        pass

    monkeypatch.setattr(routes, "aplicar_comando", _fake_aplicar)
    monkeypatch.setattr(routes, "_responder_grupo", _fake_responder)
    minio, arq = FakeMinio(), FakeArq()
    res = await routes._processar_comprovante_grupo(
        FakeConn(),
        _request(minio, arq),
        _img(caption=f"IA pausa #{_NUMERO}"),
        (b"\xff\xd8\xffimg", "image/jpeg"),
        "Fernando",
        None,
    )
    assert res == {"status": "processed"}
    assert arq.jobs == []  # OCR nao acionado
    assert len(aplicados) == 1
    assert aplicados[0]["comando"] == "pausar_ia"


async def test_sem_ancora_pede_numero(monkeypatch) -> None:
    """Sem quote e sem #N na legenda -> recuperacao (#N obrigatorio), nao enfileira."""
    respostas: list[str] = []

    async def _fake_responder(settings: Any, conn: Any, msg: Any, texto: str, **k: Any) -> None:
        respostas.append(texto)

    monkeypatch.setattr(routes, "_responder_grupo", _fake_responder)
    minio, arq = FakeMinio(), FakeArq()
    res = await routes._processar_comprovante_grupo(
        FakeConn(), _request(minio, arq), _img(), (b"img", "image/jpeg"), "modelo", None
    )
    assert res == {"status": "invalid"}
    assert arq.jobs == []
    assert respostas and "número" in respostas[0].lower()


async def test_sem_midia_pede_valor(monkeypatch) -> None:
    """Sem bytes de midia (download falhou / MinIO off) -> pede valor por texto, nao enfileira."""
    respostas: list[str] = []

    async def _fake_responder(settings: Any, conn: Any, msg: Any, texto: str, **k: Any) -> None:
        respostas.append(texto)

    monkeypatch.setattr(routes, "_responder_grupo", _fake_responder)
    arq = FakeArq()
    res = await routes._processar_comprovante_grupo(
        FakeConn(), _request(FakeMinio(), arq), _img(caption=f"#{_NUMERO}"), None, "modelo", None
    )
    assert res == {"status": "invalid"}
    assert arq.jobs == []
    assert respostas and "valor" in respostas[0].lower()


# --- Worker fechar_via_comprovante ---------------------------------------------------------------


class _ConnW:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: Any = None) -> _Result:
        return _Result([self._row] if self._row else [])


class _PoolW:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    @asynccontextmanager
    async def connection(self):
        yield _ConnW(self._row)


class _FakeEvolution:
    def __init__(self) -> None:
        self.enviados: list[dict[str, Any]] = []

    async def enviar_texto(self, **kw: Any) -> str:
        self.enviados.append(kw)
        return "ECO-1"


def _ctx(row: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "db_pool": _PoolW(row),
        "minio": object(),
        "settings": SimpleNamespace(minio_bucket_media="media", openrouter_model_vision_pix=None),
        "evolution": _FakeEvolution(),
        "vision_client": object(),
    }


def _row(estado: str = "Em_execucao") -> dict[str, Any]:
    return {
        "numero_curto": _NUMERO,
        "estado": estado,
        "conversa_id": _CONVERSA,
        "coordenacao_chat_id": "120363000000000000@g.us",
        "evolution_instance_id": "inst-a",
    }


async def test_worker_fecha_com_valor_lido(monkeypatch) -> None:
    aplicados: list[dict[str, Any]] = []

    async def _fake_baixar(*a: Any, **k: Any) -> bytes:
        return b"\xff\xd8\xffimg"

    async def _fake_ocr(*a: Any, **k: Any) -> ExtracaoPix:
        return ExtracaoPix(valor=Decimal("1500.00"), plausibilidade_visual=True, confianca="alta")

    async def _fake_aplicar(conn: Any, **k: Any) -> None:
        aplicados.append(k)

    monkeypatch.setattr(cf, "_baixar_minio", _fake_baixar)
    monkeypatch.setattr(cf, "_extrair_via_openrouter", _fake_ocr)
    monkeypatch.setattr(cf, "aplicar_comando", _fake_aplicar)

    ctx = _ctx(_row())
    await cf.fechar_via_comprovante(
        ctx, atendimento_id=str(_ATEND), object_key="k.jpg", evolution_message_id="IMG-1"
    )
    assert len(aplicados) == 1
    assert aplicados[0]["comando"] == "registrar_fechado"
    assert aplicados[0]["autor"] == "modelo"
    assert aplicados[0]["payload"]["valor_final"] == Decimal("1500.00")
    assert aplicados[0]["payload"]["forma_pagamento"] == "pix"
    # Eco de confirmacao no grupo (nunca sucesso silencioso).
    ev: _FakeEvolution = ctx["evolution"]
    assert ev.enviados and "fechado" in ev.enviados[0]["texto"].lower()


async def test_worker_ja_fechado_no_op(monkeypatch) -> None:
    aplicados: list[Any] = []

    async def _fake_aplicar(conn: Any, **k: Any) -> None:
        aplicados.append(k)

    monkeypatch.setattr(cf, "aplicar_comando", _fake_aplicar)
    ctx = _ctx(_row(estado="Fechado"))
    await cf.fechar_via_comprovante(
        ctx, atendimento_id=str(_ATEND), object_key="k.jpg", evolution_message_id="IMG-1"
    )
    assert aplicados == []  # nao refecha


async def test_worker_sem_valor_pede_texto(monkeypatch) -> None:
    aplicados: list[Any] = []

    async def _fake_baixar(*a: Any, **k: Any) -> bytes:
        return b"\xff\xd8\xffimg"

    async def _fake_ocr(*a: Any, **k: Any) -> ExtracaoPix:
        return ExtracaoPix(valor=None, plausibilidade_visual=True, confianca="baixa")

    async def _fake_aplicar(conn: Any, **k: Any) -> None:
        aplicados.append(k)

    monkeypatch.setattr(cf, "_baixar_minio", _fake_baixar)
    monkeypatch.setattr(cf, "_extrair_via_openrouter", _fake_ocr)
    monkeypatch.setattr(cf, "aplicar_comando", _fake_aplicar)

    ctx = _ctx(_row())
    await cf.fechar_via_comprovante(
        ctx, atendimento_id=str(_ATEND), object_key="k.jpg", evolution_message_id="IMG-1"
    )
    assert aplicados == []  # sem valor legivel, nao fabrica valor_final
    ev: _FakeEvolution = ctx["evolution"]
    assert ev.enviados and "valor" in ev.enviados[0]["texto"].lower()


# --- Parser: quote de imagem ---------------------------------------------------------------------


def test_quoted_id_le_quote_de_imagem() -> None:
    """A modelo responde o card COM a foto: o stanzaId vive em imageMessage.contextInfo."""
    payload = {
        "instance": "inst-a",
        "data": {
            "key": {"id": "IMG-1", "remoteJid": "120363@g.us", "fromMe": True},
            "message": {
                "imageMessage": {
                    "url": "https://x/y.enc",
                    "mimetype": "image/jpeg",
                    "caption": "#5",
                    "contextInfo": {"stanzaId": "CARD-XYZ"},
                },
                "base64": "aGVsbG8=",
            },
        },
    }
    msg = extrair_mensagem(payload)
    assert msg is not None
    assert msg.tipo == "imagem"
    assert msg.quoted_message_id == "CARD-XYZ"
    assert msg.caption == "#5"
