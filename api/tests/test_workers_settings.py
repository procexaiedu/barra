"""Smoke test para WorkerSettings ARQ — garante que cron jobs estão registrados."""

from barra.workers.settings import WorkerSettings


def test_worker_settings_tem_cron_jobs_essenciais() -> None:
    nomes = {job.name for job in WorkerSettings.cron_jobs}
    assert {"timeout_interno", "confirmar_em_execucao", "timeout_longo", "limpar_midias"} <= nomes


def test_worker_settings_tem_lifecycle() -> None:
    assert callable(WorkerSettings.on_startup)
    assert callable(WorkerSettings.on_shutdown)


def test_worker_settings_redis_configurado() -> None:
    rs = WorkerSettings.redis_settings
    assert rs.host
    assert rs.port


def _func_por_nome(nome: str) -> object:
    for f in WorkerSettings.functions:
        if f.name == nome:
            return f
    raise AssertionError(f"funcao ARQ {nome!r} nao registrada")


def test_processar_turno_max_tries_e_keep_result() -> None:
    # turno caro: max_tries=2 (nao reinvoca o Sonnet 5x) + keep_result=0 (invariante do re-enqueue).
    f = _func_por_nome("processar_turno")
    assert f.max_tries == 2  # type: ignore[attr-defined]
    assert f.keep_result_s == 0  # type: ignore[attr-defined]


def test_jobs_de_envio_max_tries() -> None:
    for nome in ("enviar_card", "enviar_turno"):
        f = _func_por_nome(nome)
        assert f.max_tries == 3, nome  # type: ignore[attr-defined]
