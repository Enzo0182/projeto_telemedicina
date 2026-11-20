"""Exceções de domínio tratadas por handlers em app.main."""


class LoginRequired(Exception):
    """Usuário não autenticado: redireciona para o login."""


class AppError(Exception):
    status_code = 400
    title = "Não foi possível concluir a operação"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PermissionDenied(AppError):
    status_code = 403
    title = "Acesso negado"


class NotFound(AppError):
    status_code = 404
    title = "Não encontrado"


class Conflict(AppError):
    status_code = 409
    title = "Conflito"


class ValidationFailed(AppError):
    status_code = 422
    title = "Dados inválidos"

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors
