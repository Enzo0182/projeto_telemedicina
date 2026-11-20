"""Configurações lidas de variáveis de ambiente."""
import os
from datetime import timedelta
from zoneinfo import ZoneInfo


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


class Settings:
    def __init__(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL", "")
        if not self.database_url:
            raise RuntimeError(
                "Variável DATABASE_URL não definida. Copie .env.example para .env "
                "ou defina a variável no ambiente."
            )
        self.timezone_name = os.environ.get("APP_TIMEZONE", "America/Sao_Paulo")
        self.timezone = ZoneInfo(self.timezone_name)
        self.session_duration = timedelta(hours=float(os.environ.get("SESSION_HOURS", "8")))
        self.cookie_secure = _bool("COOKIE_SECURE", False)
        self.seed_on_start = _bool("SEED_ON_START", False)
        self.demo_password = os.environ.get("DEMO_PASSWORD", "Demo@1234")
        self.stun_urls = [u.strip() for u in os.environ.get("STUN_URLS", "").split(",") if u.strip()]

    @property
    def ice_servers(self) -> list[dict]:
        return [{"urls": self.stun_urls}] if self.stun_urls else []


settings = Settings()

# Regras de agenda
SLOT_MINUTES = 30
GAP_MINUTES = 5
# O médico pode registrar o prontuário a partir de N minutos antes do início da consulta.
RECORD_OPEN_MINUTES_BEFORE = 15
