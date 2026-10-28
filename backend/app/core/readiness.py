"""Ограниченная проверка интерфейса доверенного ML-модуля вне API-процесса."""

import os
import signal
import subprocess
import sys
import threading
import time

import anyio

_PROBE = """
import importlib
import os
import sys

try:
    module = importlib.import_module(sys.argv[1])
    ready = callable(getattr(module, "generate", None))
except BaseException:
    ready = False
os._exit(0 if ready else 1)
"""


class ModuleReadiness:
    """Кеширует успех и отказ; одновременно допускает только один subprocess.

    Проверяет тот же минимальный интерфейс, что и адаптер: callable generate,
    синхронный или асинхронный. Не вызывает его и не требует optional revise.
    Первый конкурентный запрос во время проверки получает безопасный отказ.
    """

    def __init__(self, module, *, timeout=5, cache_seconds=30):
        self.module = module
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._ready = False
        self._expires = 0.0

    async def is_ready(self):
        """Не блокирует event loop импортом, ожиданием процесса или очередью probes."""
        if time.monotonic() < self._expires:
            return self._ready
        if self._lock.locked():
            return False
        return await anyio.to_thread.run_sync(self._check)

    def _check(self):
        # Lock принадлежит потоку до reap, даже если HTTP-задача отменена.
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if time.monotonic() < self._expires:
                return self._ready
            try:
                self._ready = self._probe()
            except Exception:
                self._ready = False
            self._expires = time.monotonic() + self.cache_seconds
            return self._ready
        finally:
            self._lock.release()

    def _probe(self):
        """Не накапливает stdout/stderr и уничтожает группу процессов при завершении."""
        with subprocess.Popen(
            [sys.executable, "-c", _PROBE, self.module],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        ) as process:
            try:
                return process.wait(timeout=self.timeout) == 0
            except subprocess.TimeoutExpired:
                return False
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
