"""Prontuário demonstrativo: somente o médico responsável pela consulta edita."""
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import RECORD_OPEN_MINUTES_BEFORE
from app.errors import Conflict, PermissionDenied
from app.models import Appointment, ClinicalRecord, User, utcnow
from app.schemas import ClinicalRecordForm


def ensure_can_edit(appt: Appointment, user: User) -> None:
    if not user.is_doctor or appt.doctor_id != user.id:
        raise PermissionDenied("Somente o médico responsável pela consulta pode editar o registro clínico.")
    if not appt.is_confirmed:
        raise Conflict("Não é possível registrar informações em uma consulta cancelada.")
    opens_at = appt.start_at - timedelta(minutes=RECORD_OPEN_MINUTES_BEFORE)
    if utcnow() < opens_at:
        raise Conflict(
            f"O registro clínico fica disponível a partir de {RECORD_OPEN_MINUTES_BEFORE} minutos "
            "antes do início da consulta (durante ou após o atendimento)."
        )


def save_record(db: Session, appt: Appointment, doctor: User, form: ClinicalRecordForm) -> ClinicalRecord:
    ensure_can_edit(appt, doctor)
    record = appt.record
    if record is None:
        record = ClinicalRecord(appointment_id=appt.id, doctor_id=appt.doctor_id, patient_id=appt.patient_id,
                                chief_complaint=form.chief_complaint)
        db.add(record)
    record.chief_complaint = form.chief_complaint
    record.anamnesis = form.anamnesis
    record.assessment = form.assessment
    record.conduct = form.conduct
    record.notes = form.notes
    record.updated_at = utcnow()
    db.commit()
    return record
