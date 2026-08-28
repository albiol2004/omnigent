"""Concurrency regression tests for the SQLite engine pool."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import monotonic, sleep

import pytest
from sqlalchemy.pool import QueuePool

from omnigent.db.utils import _create_engine


def test_sqlite_pool_handles_concurrent_checkouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Twenty-four simultaneous checkouts finish without QueuePool timeouts."""
    for variable in (
        "OMNIGENT_SQLITE_POOL_SIZE",
        "OMNIGENT_SQLITE_MAX_OVERFLOW",
        "OMNIGENT_SQLITE_POOL_TIMEOUT_S",
    ):
        monkeypatch.delenv(variable, raising=False)

    engine = _create_engine(f"sqlite:///{tmp_path / 'concurrency.db'}")
    assert isinstance(engine.pool, QueuePool)
    workers = 24
    all_checked_out = Barrier(workers)

    def _hold_connection() -> int:
        with engine.connect() as connection:
            result = connection.exec_driver_sql("SELECT 1").scalar()
            all_checked_out.wait(timeout=5)
            sleep(0.05)
            return result

    started = monotonic()
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(lambda _: _hold_connection(), range(workers)))
    finally:
        engine.dispose()

    assert results == [1] * workers
    assert monotonic() - started < 30
