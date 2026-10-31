"""Настройки окружения и обязательные ограничения безопасности запуска."""

from functools import lru_cache
from ipaddress import IPv6Address
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """Конфигурация из переменных PM_ и .env с безопасным производственным режимом.

    Технический срок задания включает очередь, проверку и сохранение результата.
    Он не измеряет полный путь до браузерного экспорта PPTX. Лимиты приёма
    ограничивают число заданий, а не фактическую стоимость вызовов ML.
    """

    model_config = SettingsConfigDict(
        env_prefix="PM_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    environment: str = "production"
    # Выставляется worker для процесса ML-модуля
    ml_subprocess: bool = False
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost/presentation_maker"
    redis_url: str = "redis://localhost:6379/0"
    allowed_origins: list[str] = ["http://localhost:5173"]
    allowed_hosts: list[str] = []
    ml_adapter: str = "module"
    ml_module: str = "presentation_ml"
    fixture_delay: float = Field(default=0, ge=0)
    fixture_failure: bool = False
    max_http_bytes: int = Field(default=2_000_000, gt=0)
    max_ml_bytes: int = Field(default=8_000_000, gt=0)
    job_deadline_seconds: int = Field(default=1500, gt=0, le=1500)
    max_active_per_user: int = Field(default=2, gt=0)
    max_active_jobs: int = Field(default=100, gt=0)
    max_daily_jobs_per_user: int = Field(default=20, gt=0)
    max_daily_jobs: int = Field(default=500, gt=0)
    max_jobs_per_user: int = Field(default=5000, gt=0)
    max_jobs: int = Field(default=100000, gt=0)
    max_presentations_per_user: int = Field(default=100, gt=0)
    max_presentations: int = Field(default=5000, gt=0)
    registration_enabled: bool | None = None
    max_users: int = Field(default=10000, gt=0)
    # Считаются только попытки с новым логином; занятый логин даёт 409 без расхода квоты
    registrations_per_day: int = Field(default=500, gt=0)
    session_days: int = Field(default=7, gt=0)
    session_idle_hours: int = Field(default=24, gt=0)
    pre_session_minutes: int = Field(default=20, gt=0)
    # Вход и регистрация с одного IP: класс за общим NAT не должен упираться в лимит
    auth_requests_per_minute: int = Field(default=30, gt=0)
    csrf_requests_per_minute: int = Field(default=30, gt=0)
    account_auth_requests_per_window: int = Field(default=30, gt=0)
    account_auth_window_seconds: int = Field(default=900, gt=0)
    global_auth_requests_per_minute: int = Field(default=300, gt=0)
    # Генерации и правки одного пользователя: квоты заданий не мешают слать запросы впустую
    write_requests_per_minute: int = Field(default=20, gt=0)
    password_concurrency: int = Field(default=2, gt=0)
    http_body_timeout_seconds: float = Field(default=10, gt=0)
    max_http_body_readers: int = Field(default=100, gt=0)
    # Один адрес не может занять все слоты медленной отправкой тела запроса
    max_http_body_readers_per_client: int = Field(default=20, gt=0)
    heartbeat_seconds: int = Field(default=15, gt=0)
    worker_lost_seconds: int = Field(default=120, gt=0)
    # Повторная доставка queued-задания, если сообщение потерялось в брокере. Сбой публикации
    # снимает отметку сразу, поэтому интервал не нужен короткий: иначе занятый ML-worker
    # копил бы в очереди дубли одного задания.
    dispatch_retry_seconds: int = Field(default=300, gt=0)

    @model_validator(mode="after")
    def production_safety(self):
        """Проверяет согласованность настроек и запрещает небезопасный запуск.

        Returns:
            Проверенные настройки без подмены адресов или расширения лимитов.

        Raises:
            ValueError: При недопустимом окружении, адресах, интервалах либо
                небезопасных производственных настройках ML, учётных данных и TLS.
        """
        if self.environment not in {"production", "development", "test"}:
            raise ValueError("Unknown environment")
        if self.ml_adapter not in {"module", "fixture"}:
            raise ValueError("Unknown ML adapter")
        if self.environment == "production" and self.ml_adapter == "fixture":
            raise ValueError("Fixture ML is forbidden in production")
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("Explicit allowed origins required")
        if self.worker_lost_seconds <= self.heartbeat_seconds:
            raise ValueError("Worker loss threshold must exceed heartbeat interval")
        if self.environment == "production" and any(
            not origin.startswith("https://") for origin in self.allowed_origins
        ):
            raise ValueError("Production origins require HTTPS")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or "*" in parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Allowed origins must be exact HTTP(S) origins")
            # urlsplit откладывает проверку порта до обращения к свойству port.
            _ = parsed.port
        for host in self.allowed_hosts:
            if not host or any(ord(c) <= 32 or c in "*/@?#\\[]" for c in host):
                raise ValueError("Allowed hosts must be explicit hostnames")
            if ":" in host:
                # Двоеточия допустимы только внутри IPv6 без скобок, но не как host:port.
                IPv6Address(host)
        # Процесс ML не подключается к БД и Redis и не получает их адреса (см. worker.call_ml)
        if self.environment == "production" and not self.ml_subprocess:
            database = make_url(self.database_url)
            redis = urlsplit(self.redis_url)
            # Плюс пароли из compose.yaml и CI: демо-стенд нельзя перенести в production как есть
            weak_passwords = {
                "postgres",
                "password",
                "changeme",
                "redis",
                "local-demo-only",
                "ci-only-password",
            }
            # Query передаётся psycopg поверх authority URL. Разрешаем только
            # настройки, не меняющие пользователя, пароль, адрес и базу данных;
            # неизвестные параметры (включая service/passfile) запрещены.
            database_options = {
                "sslmode",
                "sslrootcert",
                "sslcert",
                "sslkey",
                "sslpassword",
                "sslcrl",
                "sslcrldir",
                "sslsni",
                "ssl_min_protocol_version",
                "ssl_max_protocol_version",
                "connect_timeout",
                "application_name",
                "keepalives",
                "keepalives_idle",
                "keepalives_interval",
                "keepalives_count",
                "tcp_user_timeout",
                "target_session_attrs",
                "channel_binding",
                "gssencmode",
            }
            if (
                database.drivername != "postgresql+psycopg"
                or not database.database
                or not database.username
                or any(key not in database_options for key in database.query)
                or any(not isinstance(value, str) for value in database.query.values())
                or database.username.lower() in {"postgres", "root"}
                or not database.password
                or database.password.lower() in weak_passwords
            ):
                raise ValueError("Production requires dedicated database credentials")
            if (
                redis.scheme not in {"redis", "rediss"}
                or not redis.hostname
                or not redis.password
                or unquote(redis.password).lower() in weak_passwords
            ):
                raise ValueError("Production requires authenticated Redis")
            local_hosts = {"localhost", "127.0.0.1", "::1"}
            if database.host not in local_hosts and database.query.get("sslmode") != "verify-full":
                raise ValueError("Remote production PostgreSQL requires sslmode=verify-full")
            if redis.hostname not in local_hosts and redis.scheme != "rediss":
                raise ValueError("Remote production Redis requires TLS")
            redis_options = parse_qs(redis.query, keep_blank_values=True)
            if redis.scheme == "rediss" and (
                any(v.lower() != "required" for v in redis_options.get("ssl_cert_reqs", []))
                or any(
                    v.lower() not in {"true", "1"}
                    for v in redis_options.get("ssl_check_hostname", [])
                )
            ):
                raise ValueError("Production Redis TLS verification cannot be disabled")
        return self

    @property
    def registration_open(self) -> bool:
        """Учитывает явный допуск; по умолчанию регистрация закрыта только в production."""
        if self.registration_enabled is not None:
            return self.registration_enabled
        return self.environment != "production"

    @property
    def secure_cookie(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_name(self) -> str:
        return "__Host-session" if self.secure_cookie else "pm-dev-session"


@lru_cache
def get_settings() -> Settings:
    """Возвращает проверенную конфигурацию, кешируемую в пределах процесса."""
    return Settings()
