"""Внешний watchdog подпроцесса: не исполняет и не импортирует код ML."""

import os
import selectors
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime


def supervise(command: list[str], deadline: datetime, parent_fd: int) -> int:
    """Останавливает всю группу по deadline или закрытию lifeline воркера.

    Запускается лидером отдельной процессной группы. Дочерний процесс наследует
    только транспорт stdin/stdout, но не lifeline. Поэтому SIGKILL воркера
    обнаруживается даже при нативном зависании дочернего процесса.
    """
    if os.getpgrp() != os.getpid():
        raise RuntimeError("Supervisor requires a private process group")
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    expires = time.monotonic() + max(0, remaining)
    os.set_blocking(parent_fd, False)

    def terminate():
        os.killpg(os.getpgrp(), signal.SIGKILL)

    with selectors.DefaultSelector() as selector:
        selector.register(parent_fd, selectors.EVENT_READ)
        if remaining <= 0 or selector.select(0):
            terminate()
        child = subprocess.Popen(
            command,
            stdin=sys.stdin.buffer,
            stdout=sys.stdout.buffer,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        try:
            while True:
                remaining = min(
                    expires - time.monotonic(), (deadline - datetime.now(UTC)).total_seconds()
                )
                if remaining <= 0 or selector.select(min(remaining, 0.1)):
                    terminate()
                status = child.poll()
                if status is not None:
                    return status if status >= 0 else 128 - status
        finally:
            # При обычной ошибке самого supervisor потомки также не остаются жить.
            if child.poll() is None:
                terminate()


def main():
    deadline = datetime.fromisoformat(sys.argv[1])
    parent_fd = int(sys.argv[2])
    command = sys.argv[3:]
    if not command:
        return 2
    return supervise(command, deadline, parent_fd)


if __name__ == "__main__":
    sys.exit(main())
