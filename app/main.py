import logging
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import SESSION_COOKIE, user_from_token
from app.database import SessionLocal
from app.errors import AppError, LoginRequired
from app.routers import appointments, auth, doctor, patient, signaling
from app.web import BASE_DIR, redirect, render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Telemedicina — protótipo acadêmico", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

for r in (auth.router, patient.router, doctor.router, appointments.router, signaling.router):
    app.include_router(r)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Proteção simples contra CSRF: requisições POST de outra origem são recusadas
    # (além do cookie de sessão SameSite=Lax).
    if request.method == "POST":
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return HTMLResponse("Origem da requisição não permitida.", status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith(("/consultas", "/paciente", "/medico")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def _user_for_error(request: Request):
    try:
        with SessionLocal() as db:
            return user_from_token(db, request.cookies.get(SESSION_COOKIE))
    except Exception:
        return None


def _error_page(request: Request, status: int, title: str, message: str):
    return render(request, "error.html", {"status": status, "title": title, "message": message},
                  user=_user_for_error(request), status_code=status)


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return redirect(f"/login?proximo={quote(target)}", "Entre na sua conta para continuar.", "aviso")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return _error_page(request, exc.status_code, exc.title, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return _error_page(request, 400, "Requisição inválida", "Os dados enviados estão incompletos ou em formato inválido.")


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    titles = {404: "Página não encontrada", 405: "Método não permitido"}
    return _error_page(request, exc.status_code, titles.get(exc.status_code, "Erro"),
                       "Verifique o endereço ou volte para a página inicial." if exc.status_code == 404 else str(exc.detail))


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logging.getLogger("telemed").exception("Erro inesperado em %s %s", request.method, request.url.path)
    return _error_page(request, 500, "Erro interno", "Ocorreu um erro inesperado. Tente novamente.")


@app.get("/saude", include_in_schema=False)
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return JSONResponse({"status": "ok"})
