"""DEPLOY-01: a chave secreta do MinIO vem do Swarm secret (padrão *_FILE), não do env/git."""

from pathlib import Path

import pytest

from barra.settings import Settings


def test_secret_key_vem_do_arquivo_e_vence_o_inline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = tmp_path / "minio_secret_key"
    arquivo.write_text("  segredo-do-swarm\n", encoding="utf-8")
    monkeypatch.setenv("MINIO_SECRET_KEY_FILE", str(arquivo))

    # O arquivo é a fonte de verdade: vence até o valor inline (a chave nunca vive no env).
    s = Settings(_env_file=None, minio_secret_key="inline-vazado")
    assert s.minio_secret_key == "segredo-do-swarm"


def test_sem_file_usa_o_valor_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINIO_SECRET_KEY_FILE", raising=False)
    s = Settings(_env_file=None, minio_secret_key="inline")
    assert s.minio_secret_key == "inline"


def test_file_inexistente_cai_no_inline_sem_quebrar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FILE apontando p/ caminho inexistente não derruba o boot — cai no valor inline.
    monkeypatch.setenv("MINIO_SECRET_KEY_FILE", str(tmp_path / "nao-existe"))
    s = Settings(_env_file=None, minio_secret_key="inline")
    assert s.minio_secret_key == "inline"
