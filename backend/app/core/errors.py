class AppError(Exception):
    """Ошибка приложения с данными, безопасными для публичного HTTP-ответа.

    Args:
        status: HTTP-статус ответа.
        code: Стабильный машинный код ошибки.
        message: Сообщение пользователю на русском без секретов и приватного ввода.

    Attributes:
        status: HTTP-статус ответа.
        code: Машинный код, также используемый как текст исключения.
        message: Публичное сообщение об ошибке.
    """

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)
