"""Inicialização usada no contêiner: aplica migrações, popula (opcional) e inicia o servidor."""
import os
import subprocess
import sys
import time

from sqlalchemy import create_engine, text


def wait_for_db(url: str, attempts: int = 30) -> None:
    engine = create_engine(url, pool_pre_ping=True)
    for i in range(attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception:
            print(f"Aguardando o banco de dados ({i + 1}/{attempts})…", flush=True)
            time.sleep(2)
    sys.exit("Banco de dados indisponível.")


def main() -> None:
    from app.config import settings

    wait_for_db(settings.database_url)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    if settings.seed_on_start:
        from scripts.seed import seed
        seed(reset=False)
    port = os.environ.get("PORT", "8000")
    os.execvp(sys.executable, [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
                               "--port", port, "--proxy-headers"])


if __name__ == "__main__":
    main()
