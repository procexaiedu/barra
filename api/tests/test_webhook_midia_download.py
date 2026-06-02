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
