"""SEC-03: `_baixar_midia` endurecido contra SSRF (host fora da allowlist) e DoS (corpo gigante)."""

import httpx
import pytest
import respx

from barra.webhook.routes import _MAX_DOWNLOADS_MIDIA, _SEM_DOWNLOAD_MIDIA, _baixar_midia

_BASE = "https://evo.example.com"
_LEGIT = f"{_BASE}/media/abc.jpg"


@respx.mock
@pytest.mark.asyncio
async def test_host_fora_da_allowlist_e_recusado() -> None:
    # Host diferente do evolution_base_url → SSRF: recusa sem nem chamar a rede.
    rota = respx.get("http://169.254.169.254/latest/meta-data").mock(
        return_value=httpx.Response(200, content=b"segredo", headers={"content-type": "text/plain"})
    )
    out = await _baixar_midia("http://169.254.169.254/latest/meta-data", _BASE, 25 * 1024 * 1024)
    assert out is None
    assert not rota.called


@respx.mock
@pytest.mark.asyncio
async def test_corpo_acima_do_limite_aborta() -> None:
    respx.get(_LEGIT).mock(
        return_value=httpx.Response(
            200, content=b"x" * 2048, headers={"content-type": "image/jpeg"}
        )
    )
    out = await _baixar_midia(_LEGIT, _BASE, 1024)  # limite < corpo
    assert out is None


@respx.mock
@pytest.mark.asyncio
async def test_midia_legitima_da_evolution_passa() -> None:
    respx.get(_LEGIT).mock(
        return_value=httpx.Response(
            200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"}
        )
    )
    out = await _baixar_midia(_LEGIT, _BASE, 25 * 1024 * 1024)
    assert out == (b"\xff\xd8jpeg", "image/jpeg")


@respx.mock
@pytest.mark.asyncio
async def test_redirect_nao_e_seguido() -> None:
    # follow_redirects=False: o 302 para host interno não vira download do alvo interno.
    respx.get(_LEGIT).mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )
    interno = respx.get("http://169.254.169.254/").mock(
        return_value=httpx.Response(200, content=b"segredo")
    )
    out = await _baixar_midia(_LEGIT, _BASE, 25 * 1024 * 1024)
    # Redirect não seguido vira erro → recusa; o host interno nunca é tocado.
    assert not interno.called
    assert out is None


@respx.mock
@pytest.mark.asyncio
async def test_concorrencia_excedida_recusa_sem_baixar() -> None:
    # Anti-DoS: com todos os slots de download em voo, a próxima mídia é recusada
    # (fail-fast) sem tocar a rede, em vez de enfileirar espera ilimitada sob burst.
    rota = respx.get(_LEGIT).mock(
        return_value=httpx.Response(
            200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"}
        )
    )
    for _ in range(_MAX_DOWNLOADS_MIDIA):
        await _SEM_DOWNLOAD_MIDIA.acquire()
    try:
        out = await _baixar_midia(_LEGIT, _BASE, 25 * 1024 * 1024)
        assert out is None
        assert not rota.called
    finally:
        for _ in range(_MAX_DOWNLOADS_MIDIA):
            _SEM_DOWNLOAD_MIDIA.release()


@respx.mock
@pytest.mark.asyncio
async def test_logs_nao_vazam_media_url_crua(caplog: pytest.LogCaptureFixture) -> None:
    """R3: a media_url da Evolution carrega path/token da mídia do cliente (PII).

    Os warnings de _baixar_midia logam só o host (sinal de SSRF no host_negado, host conhecido
    nos demais), nunca a URL crua com path/query/token.
    """
    token = "TOKENSECRETO123"

    # host fora da allowlist (SSRF): o host aparece como sinal; token/path não.
    with caplog.at_level("WARNING", logger="barra.webhook.routes"):
        out = await _baixar_midia(f"http://169.254.169.254/steal?mediaKey={token}", _BASE, 1024)
    assert out is None
    assert token not in caplog.text
    assert "/steal" not in caplog.text
    assert "169.254.169.254" in caplog.text

    caplog.clear()

    # host legítimo, corpo acima do limite: host conhecido aparece; token/path não.
    url_com_token = f"{_BASE}/m/x.jpg?token={token}"
    respx.get(url_com_token).mock(
        return_value=httpx.Response(
            200, content=b"x" * 2048, headers={"content-type": "image/jpeg"}
        )
    )
    with caplog.at_level("WARNING", logger="barra.webhook.routes"):
        out = await _baixar_midia(url_com_token, _BASE, 1024)
    assert out is None
    assert token not in caplog.text
    assert "/m/x.jpg" not in caplog.text
    assert "evo.example.com" in caplog.text
