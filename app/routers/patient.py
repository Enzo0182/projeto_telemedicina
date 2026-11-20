from itertools import groupby

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auth import require_patient
from app.database import get_db
from app.errors import Conflict, NotFound, ValidationFailed
from app.models import User
from app.schemas import BookingForm, parse_form
from app.services import appointments as appt_service
from app.services.availability import available_slots
from app.services.users import get_doctor, list_doctors, list_specialties
from app.web import local_date_key, redirect, render

router = APIRouter()


@router.get("/paciente")
def dashboard(request: Request, user: User = Depends(require_patient), db: Session = Depends(get_db)):
    return render(request, "patient_dashboard.html", {
        "upcoming": appt_service.upcoming_for(db, user),
        "cancelled": appt_service.cancelled_for(db, user)[:5],
    }, user=user)


@router.get("/medicos")
def doctors(request: Request, especialidade: str | None = None,
            user: User = Depends(require_patient), db: Session = Depends(get_db)):
    docs = list_doctors(db, especialidade or None)
    return render(request, "doctors.html", {
        "doctors": [(d, len(available_slots(db, d.id))) for d in docs],
        "specialties": list_specialties(db),
        "selected": especialidade or "",
    }, user=user)


@router.get("/medicos/{doctor_id}")
def doctor_detail(request: Request, doctor_id: int, user: User = Depends(require_patient),
                  db: Session = Depends(get_db)):
    doctor = get_doctor(db, doctor_id)
    slots = available_slots(db, doctor_id)
    days = [(key, list(items)) for key, items in groupby(slots, key=lambda s: local_date_key(s["start"]))]
    return render(request, "doctor_detail.html", {"doctor": doctor, "days": days}, user=user)


@router.get("/agendar")
def booking_confirm_page(request: Request, medico: int, inicio: str,
                         user: User = Depends(require_patient), db: Session = Depends(get_db)):
    try:
        form = parse_form(BookingForm, {"doctor_id": medico, "start_at": inicio})
    except ValidationFailed:
        return redirect(f"/medicos/{medico}", "Horário inválido. Escolha um horário da lista.", "erro")
    doctor = get_doctor(db, form.doctor_id)
    start = form.start_datetime
    still_free = any(s["start"] == start for s in available_slots(db, doctor.id))
    if not still_free:
        return redirect(f"/medicos/{doctor.id}", appt_service.SLOT_UNAVAILABLE, "erro")
    return render(request, "booking_confirm.html", {"doctor": doctor, "start": start, "start_iso": inicio},
                  user=user)


@router.post("/agendar")
def booking_submit(doctor_id: str = Form(""), start_at: str = Form(""),
                   user: User = Depends(require_patient), db: Session = Depends(get_db)):
    try:
        form = parse_form(BookingForm, {"doctor_id": doctor_id, "start_at": start_at})
        appt = appt_service.book(db, user, form.doctor_id, form.start_datetime)
    except ValidationFailed:
        return redirect("/medicos", "Dados de agendamento inválidos.", "erro")
    except (Conflict, NotFound) as exc:
        target = f"/medicos/{doctor_id}" if doctor_id.isdigit() else "/medicos"
        return redirect(target, exc.message, "erro")
    return redirect(f"/consultas/{appt.id}", "Consulta confirmada com sucesso!")


@router.get("/paciente/historico")
def history(request: Request, user: User = Depends(require_patient), db: Session = Depends(get_db)):
    return render(request, "history.html", {"appointments": appt_service.history_for_patient(db, user)}, user=user)
