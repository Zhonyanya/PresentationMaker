"""Ограниченный обмен с запущенным подпроцессом; не песочница и не ML-адаптер."""

import os
import queue
import selectors
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

# Сколько дочитывать stdout после выхода процесса, если канал не закрылся
EXIT_DRAIN_SECONDS = 1.0


def exchange(
    process,
    payload: bytes,
    *,
    max_bytes: int,
    deadline: datetime,
    heartbeat_seconds: float,
    heartbeat: Callable[[], bool],
    heartbeat_grace: float = 0,
) -> bytes:
    """Передаёт ввод и читает вывод без блокировки на заполненных каналах.

    Завершение процесса и очистку его группы обеспечивает вызывающий код,
    в том числе при ошибке обмена. Heartbeat выполняется отдельно: задержка
    БД не должна останавливать чтение stdout и контроль deadline.

    Args:
        process: Запущенный процесс с открытыми бинарными stdin и stdout.
        payload: Полное содержимое ввода; после отправки stdin закрывается.
        max_bytes: Максимальное число байтов stdout, проверяемое во время чтения.
        deadline: Абсолютный срок завершения с часовым поясом UTC.
        heartbeat_seconds: Интервал подтверждения активности в секундах.
        heartbeat: Функция подтверждения; False означает потерю права на выполнение.
        heartbeat_grace: Сколько секунд после последнего успешного подтверждения
            терпеть исключения heartbeat (временный сбой БД), прежде чем прервать вызов.
            False от heartbeat прерывает вызов сразу.

    Returns:
        Накопленные байты stdout после его закрытия и завершения процесса.

    Raises:
        TimeoutError: Если истёк срок или подтверждение активности вернуло False.
        ValueError: Если вывод превышает max_bytes.
    """
    output = bytearray()
    offset = 0
    stdout_open = True
    next_heartbeat = time.monotonic() + heartbeat_seconds
    last_confirmed = time.monotonic()
    exited_at = None
    pending_heartbeat = False
    replies = queue.Queue(maxsize=1)

    def check_heartbeat():
        try:
            replies.put((heartbeat(), None))
        except Exception as exc:
            replies.put((False, exc))

    with selectors.DefaultSelector() as selector:
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE, "input")
        selector.register(process.stdout, selectors.EVENT_READ, "output")
        while stdout_open or process.poll() is None:
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise TimeoutError
            now = time.monotonic()
            # Процесс завершился, но stdout держит открытым его потомок: дочитываем
            # то, что уже записано, и не ждём EOF до самого deadline.
            if process.poll() is not None:
                exited_at = exited_at or now
                if now - exited_at > EXIT_DRAIN_SECONDS:
                    break
            if pending_heartbeat:
                try:
                    active, error = replies.get_nowait()
                except queue.Empty:
                    pass
                else:
                    pending_heartbeat = False
                    if error is not None:
                        # Разовый таймаут БД не должен убивать долгий платный вызов ML
                        if time.monotonic() - last_confirmed >= heartbeat_grace:
                            raise error
                    elif not active:
                        raise TimeoutError
                    else:
                        last_confirmed = time.monotonic()
                    next_heartbeat = time.monotonic() + heartbeat_seconds
            if not pending_heartbeat and now >= next_heartbeat:
                pending_heartbeat = True
                threading.Thread(target=check_heartbeat, daemon=True).start()
            if pending_heartbeat:
                timeout = min(remaining, 0.05)
            else:
                timeout = min(remaining, max(0, next_heartbeat - time.monotonic()), 0.2)
            for key, _ in selector.select(timeout):
                if key.data == "input":
                    try:
                        offset += os.write(key.fd, payload[offset : offset + 65536])
                    except BrokenPipeError:
                        offset = len(payload)
                    except BlockingIOError:
                        continue
                    if offset == len(payload):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                else:
                    try:
                        chunk = os.read(key.fd, min(65536, max_bytes - len(output) + 1))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        stdout_open = False
                        selector.unregister(key.fileobj)
                    elif len(output) + len(chunk) > max_bytes:
                        raise ValueError("Excessive subprocess response")
                    else:
                        output.extend(chunk)
    return bytes(output)
