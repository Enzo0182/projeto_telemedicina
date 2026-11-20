from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auth import require_doctor
from app.config import settings
from app.database import get_db
from app.errors import Conflict, NotFound, ValidationFailed
from app.models import User, utcnow
from app.schemas import AvailabilityForm, parse_form
from app.services import appointments as appt_service
from app.services.availability import (
    booked_intervals, create_period, delete_period, list_future_periods, period_slots,
)
from app.web import redirect, render

router = APIRouter()


@router.get("/medico")
def dashboard(request: Request, user: User = Depends(require_doctor), db: Session = Depends(get_db)):
    return render(request, "doctor_dashboard.html", {
        "upcoming": appt_service.upcoming_for(db, user),
        "past": appt_service.past_for(db, user)[:20],
        "cancelled": appt_service.cancelled_for(db, user)[:5],
    }, user=user)


def _availability_page(request: Request, user: User, db: Session, *, values=None, errors=None, status_code=200):
    periods = list_future_periods(db, user.id)
    now = utcnow()
    rows = []
    for p in periods:
        slots = period_slots(p, booked_intervals(db, user.id, p.start_at, p.end_at), now)
        rows.append({"period": p, "slots": slots,
                     "free": sum(1 for s in slots if s["available"]),
                     "taken": sum(1 for s in slots if s["taken"])})
    return render(request, "availability.html", {
        "rows": rows, "values": values or {}, "errors": errors or {},
        "today": now.astimezone(settings.timezone).date().isoformat(),
    }, user=user, status_code=status_code)


@router.get("/medico/disponibilidade")
def availability(request: Request, user: User = Depends(require_doctor), db: Session = Depends(get_db)):
    return _availability_page(request, user, db)


@router.post("/medico/disponibilidade")
def availability_add(request: Request, day: str = Form(""), start_time: str = Form(""), end_time: str = Form(""),
                     user: User = Depends(require_doctor), db: Session = Depends(get_db)):
    values = {"day": day, "start_time": start_time, "end_time": end_time}
    try:
        form = parse_form(AvailabilityForm, values)
        create_period(db, user, *form.parsed)
    except ValidationFailed as exc:
        return _availability_page(request, user, db, values=values, errors=exc.errors, status_code=422)
    except Conflict as exc:
        return _availability_page(request, user, db, values=values, errors={"__all__": exc.message},
                                  status_code=409)
    return redirect("/medico/disponibilidade", "Período de disponibilidade cadastrado.")


@router.post("/medico/disponibilidade/{period_id}/excluir")
def availability_delete(period_id: int, user: User = Depends(require_doctor), db: Session = Depends(get_db)):
    try:
        delete_period(db, user, period_id)
    except (Conflict, NotFound) as exc:
        return redirect("/medico/disponibilidade", exc.message, "erro")
    return redirect("/medico/disponibilidade", "Período excluído.")
