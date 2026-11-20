from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.errors import Conflict, NotFound
from app.models import ROLE_DOCTOR, ROLE_PATIENT, DoctorProfile, User
from app.schemas import RegisterForm
from app.security import hash_password


def register_patient(db: Session, form: RegisterForm) -> User:
    if db.scalar(select(User.id).where(User.email == form.email)) is not None:
        raise Conflict("Já existe uma conta com este e-mail.")
    user = User(name=form.name, email=form.email, password_hash=hash_password(form.password), role=ROLE_PATIENT)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("Já existe uma conta com este e-mail.") from None
    return user


def create_doctor(db: Session, *, name: str, email: str, password: str, specialty: str,
                  bio: str = "", registry: str = "") -> User:
    email = email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise Conflict(f"Já existe uma conta com o e-mail {email}.")
    user = User(name=name, email=email, password_hash=hash_password(password), role=ROLE_DOCTOR)
    user.doctor_profile = DoctorProfile(specialty=specialty, bio=bio, registry=registry)
    db.add(user)
    db.commit()
    return user


def list_doctors(db: Session, specialty: str | None = None) -> list[User]:
    stmt = (
        select(User)
        .join(DoctorProfile)
        .options(joinedload(User.doctor_profile))
        .where(User.role == ROLE_DOCTOR, User.is_active.is_(True))
        .order_by(User.name)
    )
    if specialty:
        stmt = stmt.where(DoctorProfile.specialty == specialty)
    return list(db.scalars(stmt))


def list_specialties(db: Session) -> list[str]:
    return list(db.scalars(select(DoctorProfile.specialty).distinct().order_by(DoctorProfile.specialty)))


def get_doctor(db: Session, doctor_id: int) -> User:
    doctor = db.scalar(
        select(User).options(joinedload(User.doctor_profile))
        .where(User.id == doctor_id, User.role == ROLE_DOCTOR, User.is_active.is_(True))
    )
    if doctor is None:
        raise NotFound("Médico não encontrado.")
    return doctor
