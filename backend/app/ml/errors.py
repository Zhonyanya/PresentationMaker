"""Error codes allowed across the isolated ML process boundary."""

from app.core.errors import AppError

PROVIDER_FAILURE_REASONS = frozenset({'transport', 'upstream_5xx', 'blacklist', 'upstream_4xx'})


class ProviderFailure(AppError):
    def __init__(self, code, reason):
        self.reason = reason
        super().__init__(502, code, PUBLIC_ERRORS[code])


PUBLIC_ERRORS = {
    "ML_UNAVAILABLE": "ML-модуль недоступен.",
    "ML_CAPABILITY_UNAVAILABLE": "ML не поддерживает эту операцию.",
    "INVALID_ML_RESPONSE": "ML вернул документ неверного формата.",
    "GENERATION_FAILED": "Ошибка выполнения ML.",
    "NO_TABLE_COMPARISONS": "В таблицах нет распознанных сравнений по периодам.",
    "ML_PROVIDER_TIMEOUT": "GigaChat не успел ответить.",
    "ML_PROVIDER_UNAVAILABLE": "Сервис GigaChat временно недоступен.",
    "ML_PROVIDER_BUSY": "GigaChat отклонил запрос из-за лимита. Попробуйте позже.",
    "ML_PROVIDER_REJECTED": "GigaChat отклонил запрос на создание документа.",
    "ML_PROVIDER_INCOMPLETE": "GigaChat вернул неполный ответ.",
}
