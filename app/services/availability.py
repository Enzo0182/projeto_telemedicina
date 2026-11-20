"""Períodos de disponibilidade e geração de horários (30 min + 5 min de intervalo)."""
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import GAP_MINUTES, SLOT_MINUTES, settings
from app.errors import Conflict, NotFound, ValidationFailed
from app.models import STATUS_CONFIRMED, Appointment, AvailabilityPeriod, User, utcnow

SLOT = timedelta(minutes=SLOT_MINUTES)
STEP = timedelta(minutes=SLOT_MINUTES + GAP_MINUTES)
MAX_DAYS_AHEAD = 90


def slot_starts(start_at: datetime, end_at: datetime) -> Iterator[datetime]:
    """Gera os inícios de consulta dentro de um período: cada consulta dura 30 min,
    seguida de 5 min de intervalo antes da próxima."""
    t = start_at
    while t + SLOT <= end_at:
        yield t
        t += STEP


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def create_period(db: Session, doctor: User, day: date, start: time, end: time) -> AvailabilityPeriod:
    tz = settings.timezone
    start_at = datetime.combine(day, start, tzinfo=tz)
    end_at = datetime.combine(day, end, tzinfo=tz)
    now = utcnow()
    errors: dict[str, str] = {}
    if end_at <= start_at:
        errors["end_time"] = "O horário final deve ser posterior ao inicial."
    elif end_at - start_at < SLOT:
        errors["end_time"] = f"O período deve ter pelo menos {SLOT_MINUTES} minutos."
    if end_at <= now:
        errors["day"] = "O período informado já passou."
    elif day > (now.astimezone(tz).date() + timedelta(days=MAX_DAYS_AHEAD)):
        errors["day"] = f"Cadastre períodos com até {MAX_DAYS_AHEAD} dias de antecedência."
    if errors:
        raise ValidationFailed(errors)

    # Bloqueia o registro do médico para serializar alterações concorrentes de agenda.
    db.execute(select(User.id).where(User.id == doctor.id).with_for_update())
    clash = db.scalar(
        select(AvailabilityPeriod).where(
            AvailabilityPeriod.doctor_id == doctor.id,
            AvailabilityPeriod.start_at < end_at,
            AvailabilityPeriod.end_at > start_at,
        )
    )
    if clash:
        db.rollback()
        raise Conflict("Este período se sobrepõe a outro período de disponibilidade já cadastrado.")
    period = AvailabilityPeriod(doctor_id=doctor.id, start_at=start_at, end_at=end_at)
    db.add(period)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("Este período se sobrepõe a outro período de disponibilidade já cadastrado.") from None
    return period


def delete_period(db: Session, doctor: User, period_id: int) -> None:
    db.execute(select(User.id).where(User.id == doctor.id).with_for_update())
    period = db.get(AvailabilityPeriod, period_id)
    if period is None or period.doctor_id != doctor.id:
        db.rollback()
        raise NotFound("Período não encontrado.")
    booked = db.scalar(
        select(Appointment.id).where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == STATUS_CONFIRMED,
            Appointment.start_at < period.end_at,
            Appointment.end_at > period.start_at,
        ).limit(1)
    )
    if booked is not None:
        db.rollback()
        raise Conflict("Não é possível excluir: há consultas confirmadas neste período. Cancele-as antes.")
    db.delete(period)
    db.commit()


def list_future_periods(db: Session, doctor_id: int) -> list[AvailabilityPeriod]:
    return list(db.scalars(
        select(AvailabilityPeriod)
        .where(AvailabilityPeriod.doctor_id == doctor_id, AvailabilityPeriod.end_at > utcnow())
        .order_by(AvailabilityPeriod.start_at)
    ))


def booked_intervals(db: Session, doctor_id: int, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    rows = db.execute(
        select(Appointment.start_at, Appointment.end_at).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == STATUS_CONFIRMED,
            Appointment.start_at < end,
            Appointment.end_at > start,
        )
    ).all()
    return [(r.start_at, r.end_at) for r in rows]


def period_slots(period: AvailabilityPeriod, booked: list[tuple[datetime, datetime]], now: datetime) -> list[dict]:
    """Lista os horários de um período com indicação de disponibilidade."""
    slots = []
    for s in slot_starts(period.start_at, period.end_at):
        e = s + SLOT
        taken = any(_overlaps(s, e, b0, b1) for b0, b1 in booked)
        slots.append({"start": s, "end": e, "available": s > now and not taken, "taken": taken, "past": s <= now})
    return slots


def available_slots(db: Session, doctor_id: int) -> list[dict]:
    """Somente horários futuros e livres de um médico."""
    now = utcnow()
    periods = list_future_periods(db, doctor_id)
    if not periods:
        return []
    booked = booked_intervals(db, doctor_id, periods[0].start_at, periods[-1].end_at)
    result = []
    for p in periods:
        result.extend(s for s in period_slots(p, booked, now) if s["available"])
    return result


def is_valid_slot(db: Session, doctor_id: int, start_at: datetime) -> bool:
    """Confere se start_at é exatamente um início de horário gerado por algum período do médico."""
    period = db.scalar(
        select(AvailabilityPeriod).where(
            AvailabilityPeriod.doctor_id == doctor_id,
            AvailabilityPeriod.start_at <= start_at,
            AvailabilityPeriod.end_at >= start_at + SLOT,
        )
    )
    if period is None:
        return False
    return any(s == start_at for s in slot_starts(period.start_at, period.end_at))
