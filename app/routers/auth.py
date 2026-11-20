from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE, authenticate, end_session, get_current_user_optional, start_session
from app.database import get_db
from app.errors import Conflict, ValidationFailed
from app.models import User
from app.schemas import LoginForm, RegisterForm, parse_form
from app.services.users import register_patient
from app.web import home_for, redirect, render, safe_next

router = APIRouter()


@router.get("/")
def index(user: User | None = Depends(get_current_user_optional)):
    return redirect(home_for(user) if user else "/login")


@router.get("/login")
def login_page(request: Request, proximo: str | None = None,
               user: User | None = Depends(get_current_user_optional)):
    if user:
        return redirect(home_for(user))
    return render(request, "login.html", {"next": safe_next(proximo, ""), "values": {}, "errors": {}})


@router.post("/login")
def login_submit(request: Request, email: str = Form(""), password: str = Form(""),
                 next: str = Form(""), db: Session = Depends(get_db)):
    values = {"email": email}
    try:
        form = parse_form(LoginForm, {"email": email, "password": password})
    except ValidationFailed as exc:
        return render(request, "login.html", {"next": next, "values": values, "errors": exc.errors}, status_code=422)
    user = authenticate(db, form.email, form.password)
    if user is None:
        return render(request, "login.html", {
            "next": next, "values": values, "errors": {"__all__": "E-mail ou senha incorretos."},
        }, status_code=401)
    response = redirect(safe_next(next, home_for(user)), f"Bem-vindo(a), {user.name}!")
    start_session(db, user, response)
    return response


@router.get("/cadastro")
def register_page(request: Request, user: User | None = Depends(get_current_user_optional)):
    if user:
        return redirect(home_for(user))
    return render(request, "register.html", {"values": {}, "errors": {}})


@router.post("/cadastro")
def register_submit(request: Request, name: str = Form(""), email: str = Form(""), password: str = Form(""),
                    password_confirm: str = Form(""), db: Session = Depends(get_db)):
    values = {"name": name, "email": email}
    try:
        form = parse_form(RegisterForm, {"name": name, "email": email, "password": password,
                                         "password_confirm": password_confirm})
        user = register_patient(db, form)
    except ValidationFailed as exc:
        return render(request, "register.html", {"values": values, "errors": exc.errors}, status_code=422)
    except Conflict as exc:
        return render(request, "register.html", {"values": values, "errors": {"email": exc.message}},
                      status_code=409)
    response = redirect("/paciente", "Conta criada com sucesso. Você já está conectado(a).")
    start_session(db, user, response)
    return response


@router.post("/sair")
def logout(request: Request, db: Session = Depends(get_db)):
    response = redirect("/login", "Sessão encerrada.")
    end_session(db, request.cookies.get(SESSION_COOKIE), response)
    return response
