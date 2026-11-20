"""Esquemas Pydantic para validação dos formulários (mensagens em português)."""
import re
from datetime import date, datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from app.errors import ValidationFailed

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class _Form(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


def _required(value: str, label: str, max_len: int) -> str:
    if not value:
        raise ValueError(f"Informe {label}.")
    if len(value) > max_len:
        raise ValueError(f"{label[0].upper() + label[1:]} deve ter no máximo {max_len} caracteres.")
    return value


class LoginForm(_Form):
    email: str = ""
    password: str = ""

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _required(v, "o e-mail", 254).lower()

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _required(v, "a senha", 128)


class RegisterForm(_Form):
    name: str = ""
    email: str = ""
    password: str = ""
    password_confirm: str = ""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = _required(v, "o nome", 120)
        if len(v) < 3:
            raise ValueError("O nome deve ter pelo menos 3 caracteres.")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = _required(v, "o e-mail", 254).lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Informe um e-mail válido (ex.: nome@exemplo.com).")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("A senha deve ter pelo menos 8 caracteres.")
        if len(v) > 128:
            raise ValueError("A senha deve ter no máximo 128 caracteres.")
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("A senha deve conter letras e números.")
        return v

    @model_validator(mode="after")
    def _confirm(self) -> "RegisterForm":
        if self.password and self.password != self.password_confirm:
            raise ValueError("password_confirm|As senhas não conferem.")
        return self


class AvailabilityForm(_Form):
    day: str = ""
    start_time: str = ""
    end_time: str = ""

    @field_validator("day")
    @classmethod
    def _day(cls, v: str) -> str:
        if not v:
            raise ValueError("Informe a data.")
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("Data inválida.") from None
        return v

    @field_validator("start_time", "end_time")
    @classmethod
    def _time(cls, v: str) -> str:
        if not v:
            raise ValueError("Informe o horário.")
        try:
            time.fromisoformat(v)
        except ValueError:
            raise ValueError("Horário inválido (use HH:MM).") from None
        return v

    @property
    def parsed(self) -> tuple[date, time, time]:
        return date.fromisoformat(self.day), time.fromisoformat(self.start_time), time.fromisoformat(self.end_time)


class BookingForm(_Form):
    doctor_id: int
    start_at: str

    @field_validator("start_at")
    @classmethod
    def _start(cls, v: str) -> str:
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("Horário inválido.") from None
        if dt.tzinfo is None:
            raise ValueError("Horário sem fuso horário.")
        return v

    @property
    def start_datetime(self) -> datetime:
        return datetime.fromisoformat(self.start_at)


class ClinicalRecordForm(_Form):
    chief_complaint: str = ""
    anamnesis: str = ""
    assessment: str = ""
    conduct: str = ""
    notes: str = ""

    @field_validator("chief_complaint")
    @classmethod
    def _complaint(cls, v: str) -> str:
        return _required(v, "a queixa principal", 1000)

    @field_validator("anamnesis", "assessment", "conduct", "notes")
    @classmethod
    def _long_text(cls, v: str) -> str:
        if len(v) > 5000:
            raise ValueError("O texto deve ter no máximo 5000 caracteres.")
        return v


def parse_form[T: BaseModel](schema: type[T], data: dict[str, Any]) -> T:
    """Valida dados de formulário e converte erros para ValidationFailed."""
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        errors: dict[str, str] = {}
        for err in exc.errors():
            field = str(err["loc"][0]) if err["loc"] else "__all__"
            msg = err["msg"]
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, "):]
            if "|" in msg:  # validador de modelo indicando o campo
                field, msg = msg.split("|", 1)
            elif err["type"] in {"int_parsing", "int_type", "missing"}:
                msg = "Valor ausente ou inválido."
            errors.setdefault(field, msg)
        raise ValidationFailed(errors) from None
