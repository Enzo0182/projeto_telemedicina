"""Utilitários de renderização: templates Jinja2, filtros de data e mensagens flash."""
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.models import User, utcnow
from app.services.appointments import phase

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

FLASH_COOKIE = "telemed_aviso"
_WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def _local(dt: datetime) -> datetime:
    return dt.astimezone(settings.timezone)


def fmt_datetime(dt: datetime | None) -> str:
    return _local(dt).strftime("%d/%m/%Y %H:%M") if dt else ""


def fmt_date(dt: datetime) -> str:
    d = _local(dt)
    return f"{_WEEKDAYS[d.weekday()]}, {d.strftime('%d/%m/%Y')}"


def fmt_time(dt: datetime) -> str:
    return _local(dt).strftime("%H:%M")


def local_date_key(dt: datetime) -> str:
    return _local(dt).date().isoformat()


templates.env.filters.update(dt=fmt_datetime, date_long=fmt_date, hm=fmt_time, date_key=local_date_key)
templates.env.globals.update(phase=phase, timezone_name=settings.timezone_name)


def render(request: Request, name: str, context: dict[str, Any] | None = None, *,
           user: User | None = None, status_code: int = 200) -> HTMLResponse:
    flash = None
    raw = request.cookies.get(FLASH_COOKIE)
    if raw:
        try:
            kind, message = json.loads(unquote(raw))
            flash = {"kind": str(kind), "message": str(message)}
        except (ValueError, TypeError):
            flash = None
    ctx = {"user": user, "flash": flash, "now": utcnow()}
    ctx.update(context or {})
    response = templates.TemplateResponse(request, name, ctx, status_code=status_code)
    if raw:
        response.delete_cookie(FLASH_COOKIE, path="/")
    return response


def redirect(url: str, message: str | None = None, kind: str = "sucesso") -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    if message:
        response.set_cookie(FLASH_COOKIE, quote(json.dumps([kind, message])), max_age=60,
                            httponly=True, samesite="lax", path="/", secure=settings.cookie_secure)
    return response


def safe_next(url: str | None, default: str = "/") -> str:
    """Evita redirecionamento aberto: aceita apenas caminhos locais."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default


def home_for(user: User) -> str:
    return "/medico" if user.is_doctor else "/paciente"
