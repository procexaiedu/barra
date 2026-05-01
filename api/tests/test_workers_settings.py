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
