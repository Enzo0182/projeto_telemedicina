"""Rotas compartilhadas por paciente e médico vinculados a uma consulta."""
import json

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.auth import require_doctor, require_user
from app.config import settings
from app.database import get_db
from app.errors import Conflict, PermissionDenied, ValidationFailed
from app.models import User
from app.schemas import ClinicalRecordForm, parse_form
from app.services import appointments as appt_service
from app.services.records import ensure_can_edit, save_record
from app.web import redirect, render

router = APIRouter(prefix="/consultas")


@router.get("/{appointment_id}")
def detail(request: Request, appointment_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    appt = appt_service.get_for_participant(db, appointment_id, user)
    can_edit_record = True
    try:
        ensure_can_edit(appt, user)
    except (PermissionDenied, Conflict):
        can_edit_record = False
    return render(request, "appointment_detail.html", {"appt": appt, "can_edit_record": can_edit_record}, user=user)


@router.post("/{appointment_id}/cancelar")
def cancel(appointment_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        appt_service.cancel(db, appointment_id, user)
    except Conflict as exc:
        return redirect(f"/consultas/{appointment_id}", exc.message, "erro")
    return redirect(f"/consultas/{appointment_id}", "Consulta cancelada. O horário voltou a ficar disponível.")


@router.get("/{appointment_id}/sala")
def room(request: Request, appointment_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    appt = appt_service.get_for_participant(db, appointment_id, user)
    if not appt.is_confirmed:
        raise Conflict("A sala não está disponível para consultas canceladas.")
    room_config = {
        "appointmentId": appt.id,
        "role": user.role,
        "wsPath": f"/ws/consultas/{appt.id}",
        "iceServers": settings.ice_servers,
    }
    return render(request, "room.html", {"appt": appt, "room_config": json.dumps(room_config).replace("<", "\\u003c")}, user=user)


@router.get("/{appointment_id}/prontuario")
def record_form(request: Request, appointment_id: int, user: User = Depends(require_doctor),
                db: Session = Depends(get_db)):
    appt = appt_service.get_for_participant(db, appointment_id, user)
    ensure_can_edit(appt, user)
    r = appt.record
    values = {
        "chief_complaint": r.chief_complaint if r else "", "anamnesis": r.anamnesis if r else "",
        "assessment": r.assessment if r else "", "conduct": r.conduct if r else "", "notes": r.notes if r else "",
    }
    return render(request, "record_form.html", {"appt": appt, "values": values, "errors": {}}, user=user)


@router.post("/{appointment_id}/prontuario")
def record_submit(request: Request, appointment_id: int,
                  chief_complaint: str = Form(""), anamnesis: str = Form(""), assessment: str = Form(""),
                  conduct: str = Form(""), notes: str = Form(""),
                  user: User = Depends(require_doctor), db: Session = Depends(get_db)):
    appt = appt_service.get_for_participant(db, appointment_id, user)
    values = {"chief_complaint": chief_complaint, "anamnesis": anamnesis, "assessment": assessment,
              "conduct": conduct, "notes": notes}
    try:
        form = parse_form(ClinicalRecordForm, values)
    except ValidationFailed as exc:
        return render(request, "record_form.html", {"appt": appt, "values": values, "errors": exc.errors},
                      user=user, status_code=422)
    save_record(db, appt, user, form)
    return redirect(f"/consultas/{appt.id}", "Registro clínico salvo.")
