"""Regras de agendamento, acesso a consultas e cancelamento."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import RECORD_OPEN_MINUTES_BEFORE
from app.errors import Conflict, NotFound, PermissionDenied
from app.models import (
    ROLE_DOCTOR, STATUS_CANCELLED, STATUS_CONFIRMED, Appointment, User, utcnow,
)
from app.security import new_room_code
from app.services.availability import SLOT, is_valid_slot

SLOT_UNAVAILABLE = "Este horário não está mais disponível. Escolha outro horário."


def book(db: Session, patient: User, doctor_id: int, start_at: datetime) -> Appointment:
    """Agenda uma consulta revalidando a disponibilidade no banco.

    Concorrência: as linhas do médico e do paciente são bloqueadas (SELECT ... FOR UPDATE,
    sempre na mesma ordem) para serializar agendamentos simultâneos. Como garantia final,
    restrições EXCLUDE no PostgreSQL impedem consultas sobrepostas por médico e por paciente.
    """
    start_at = start_at.astimezone(timezone.utc)
    end_at = start_at + SLOT

    locked = db.scalars(
        select(User).where(User.id.in_({doctor_id, patient.id})).order_by(User.id).with_for_update()
    ).all()
    doctor = next((u for u in locked if u.id == doctor_id and u.role == ROLE_DOCTOR and u.is_active), None)
    try:
        if doctor is None:
            raise NotFound("Médico não encontrado.")
        if start_at <= utcnow():
            raise Conflict("Este horário já passou. Escolha um horário futuro.")
        if not is_valid_slot(db, doctor_id, start_at):
            raise Conflict(SLOT_UNAVAILABLE)
        doctor_busy = db.scalar(select(Appointment.id).where(
            Appointment.doctor_id == doctor_id, Appointment.status == STATUS_CONFIRMED,
            Appointment.start_at < end_at, Appointment.end_at > start_at,
        ).limit(1))
        if doctor_busy is not None:
            raise Conflict(SLOT_UNAVAILABLE)
        patient_busy = db.scalar(select(Appointment.id).where(
            Appointment.patient_id == patient.id, Appointment.status == STATUS_CONFIRMED,
            Appointment.start_at < end_at, Appointment.end_at > start_at,
        ).limit(1))
        if patient_busy is not None:
            raise Conflict("Você já possui uma consulta confirmada que conflita com este horário.")
    except Exception:
        db.rollback()
        raise

    appt = Appointment(
        doctor_id=doctor_id, patient_id=patient.id, start_at=start_at, end_at=end_at,
        status=STATUS_CONFIRMED, room_code=new_room_code(),
    )
    db.add(appt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(SLOT_UNAVAILABLE) from None
    return appt


def get_for_participant(db: Session, appointment_id: int, user: User) -> Appointment:
    """Retorna a consulta somente se o usuário for o paciente ou o médico vinculado."""
    appt = db.scalar(
        select(Appointment)
        .options(joinedload(Appointment.doctor).joinedload(User.doctor_profile),
                 joinedload(Appointment.patient), joinedload(Appointment.record))
        .where(Appointment.id == appointment_id)
    )
    if appt is None:
        raise NotFound("Consulta não encontrada.")
    if user.id not in (appt.doctor_id, appt.patient_id):
        raise PermissionDenied("Você não está vinculado a esta consulta.")
    return appt


def cancel(db: Session, appointment_id: int, user: User) -> Appointment:
    appt = get_for_participant(db, appointment_id, user)
    if not appt.is_confirmed:
        raise Conflict("Esta consulta já está cancelada.")
    if appt.start_at <= utcnow():
        raise Conflict("Não é possível cancelar uma consulta que já começou ou terminou.")
    if appt.record is not None:
        raise Conflict("Não é possível cancelar uma consulta com registro clínico.")
    appt.status = STATUS_CANCELLED
    appt.cancelled_at = utcnow()
    db.commit()
    return appt


def _list(db: Session, *conditions, desc: bool = False) -> list[Appointment]:
    order = Appointment.start_at.desc() if desc else Appointment.start_at
    return list(db.scalars(
        select(Appointment)
        .options(joinedload(Appointment.doctor).joinedload(User.doctor_profile),
                 joinedload(Appointment.patient), joinedload(Appointment.record))
        .where(*conditions).order_by(order)
    ).unique())


def upcoming_for(db: Session, user: User) -> list[Appointment]:
    owner = Appointment.doctor_id if user.is_doctor else Appointment.patient_id
    return _list(db, owner == user.id, Appointment.status == STATUS_CONFIRMED, Appointment.end_at > utcnow())


def past_for(db: Session, user: User) -> list[Appointment]:
    owner = Appointment.doctor_id if user.is_doctor else Appointment.patient_id
    return _list(db, owner == user.id, Appointment.status == STATUS_CONFIRMED, Appointment.end_at <= utcnow(), desc=True)


def cancelled_for(db: Session, user: User) -> list[Appointment]:
    owner = Appointment.doctor_id if user.is_doctor else Appointment.patient_id
    return _list(db, owner == user.id, Appointment.status == STATUS_CANCELLED, desc=True)


def history_for_patient(db: Session, patient: User) -> list[Appointment]:
    return _list(db, Appointment.patient_id == patient.id, Appointment.status == STATUS_CONFIRMED,
                 Appointment.start_at <= utcnow() + timedelta(minutes=RECORD_OPEN_MINUTES_BEFORE), desc=True)


def phase(appt: Appointment, now: datetime | None = None) -> str:
    """Situação para exibição: cancelada, agendada, em andamento ou realizada."""
    now = now or utcnow()
    if not appt.is_confirmed:
        return "cancelada"
    if now < appt.start_at:
        return "agendada"
    if now < appt.end_at:
        return "em andamento"
    return "encerrada"
