"""Popula o banco com dados FICTÍCIOS para demonstração.

Uso:
    python -m scripts.seed           # popula somente se o banco estiver vazio
    python -m scripts.seed --reset   # apaga todos os dados e popula novamente

Os horários são relativos ao momento da execução: há uma consulta "em andamento"
(iniciada há poucos minutos), uma consulta passada com prontuário e consultas futuras.
"""
import argparse
from datetime import datetime, time, timedelta

from sqlalchemy import select, text

from app.config import settings
from app.database import SessionLocal
from app.models import (
    ROLE_PATIENT, STATUS_CONFIRMED, Appointment, AvailabilityPeriod, ClinicalRecord, DoctorProfile, User, utcnow,
)
from app.security import hash_password, new_room_code
from app.services.availability import SLOT

DOCTORS = [
    ("Dra. Ana Ribeiro", "ana.ribeiro@medico.example", "Clínica Médica", "CRM-FICT 10001",
     "Atendimento clínico geral, acompanhamento de doenças crônicas e orientação preventiva (perfil fictício)."),
    ("Dr. Bruno Carvalho", "bruno.carvalho@medico.example", "Cardiologia", "CRM-FICT 10002",
     "Avaliação cardiológica de rotina e acompanhamento de hipertensão (perfil fictício)."),
    ("Dra. Carla Mendes", "carla.mendes@medico.example", "Dermatologia", "CRM-FICT 10003",
     "Orientação dermatológica e acompanhamento de lesões de pele (perfil fictício)."),
    ("Dr. Diego Nogueira", "diego.nogueira@medico.example", "Pediatria", "CRM-FICT 10004",
     "Puericultura e orientação a pais e responsáveis (perfil fictício)."),
]
PATIENTS = [
    ("Maria Souza", "maria.souza@paciente.example"),
    ("João Lima", "joao.lima@paciente.example"),
]
TABLES = ["clinical_records", "appointments", "availability_periods", "login_sessions", "doctor_profiles", "users"]


def _floor_5min(dt: datetime) -> datetime:
    return dt.replace(minute=dt.minute - dt.minute % 5, second=0, microsecond=0)


def seed(reset: bool = False) -> None:
    tz = settings.timezone
    with SessionLocal() as db:
        if reset:
            db.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
            db.commit()
        elif db.scalar(select(User.id).limit(1)) is not None:
            print("O banco já possui dados. Nada foi alterado (use --reset para recriar os dados fictícios).")
            return

        pwd_hash = hash_password(settings.demo_password)
        doctors = []
        for name, email, specialty, registry, bio in DOCTORS:
            u = User(name=name, email=email, password_hash=pwd_hash, role="medico")
            u.doctor_profile = DoctorProfile(specialty=specialty, bio=bio, registry=registry)
            db.add(u)
            doctors.append(u)
        patients = [User(name=n, email=e, password_hash=pwd_hash, role=ROLE_PATIENT) for n, e in PATIENTS]
        db.add_all(patients)
        db.flush()
        ana, bruno, carla, _diego = doctors
        maria, joao = patients

        now_local = utcnow().astimezone(tz)
        today = now_local.date()

        # Disponibilidade padrão: próximos 7 dias úteis, 08:00–12:00 e 14:00–17:30.
        for d in doctors:
            day, added = today, 0
            while added < 7:
                if day.weekday() < 5 and not (d is ana and day == today):
                    for start, end in ((time(8), time(12)), (time(14), time(17, 30))):
                        db.add(AvailabilityPeriod(doctor_id=d.id,
                                                  start_at=datetime.combine(day, start, tzinfo=tz),
                                                  end_at=datetime.combine(day, end, tzinfo=tz)))
                    added += 1
                day += timedelta(days=1)

        # Período "agora" da Dra. Ana: começa 10 min atrás, permitindo uma consulta em andamento.
        live_start = _floor_5min(now_local) - timedelta(minutes=10)
        db.add(AvailabilityPeriod(doctor_id=ana.id, start_at=live_start, end_at=live_start + timedelta(hours=3)))

        def appt(doctor: User, patient: User, start: datetime) -> Appointment:
            a = Appointment(doctor_id=doctor.id, patient_id=patient.id, start_at=start, end_at=start + SLOT,
                            status=STATUS_CONFIRMED, room_code=new_room_code())
            db.add(a)
            return a

        # 1) Consulta em andamento: Maria com Dra. Ana (para demonstrar sala e prontuário).
        appt(ana, maria, live_start)

        # 2) Consulta passada com prontuário: Maria com Dr. Bruno, 7 dias atrás.
        past_day = today - timedelta(days=7)
        past_start = datetime.combine(past_day, time(9), tzinfo=tz)
        db.add(AvailabilityPeriod(doctor_id=bruno.id, start_at=past_start, end_at=past_start + timedelta(hours=2)))
        past = appt(bruno, maria, past_start)
        db.flush()
        db.add(ClinicalRecord(
            appointment_id=past.id, doctor_id=bruno.id, patient_id=maria.id,
            chief_complaint="[FICTÍCIO] Palpitações ocasionais após esforço.",
            anamnesis="[FICTÍCIO] Relata episódios esporádicos há 2 semanas, sem síncope. Nega dor torácica.",
            assessment="[FICTÍCIO] Exame remoto sem sinais de alarme. Hipótese a esclarecer.",
            conduct="[FICTÍCIO] Orientações gerais e solicitação de exames de rotina para demonstração.",
            notes="Registro criado automaticamente pelo seed para demonstração.",
        ))

        # 3) Consulta futura: João com Dra. Carla no próximo dia útil, primeiro horário da manhã.
        nxt = today + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        appt(carla, joao, datetime.combine(nxt, time(8), tzinfo=tz))

        db.commit()

    print("Dados fictícios criados com sucesso. Senha de todas as contas: valor de DEMO_PASSWORD (padrão Demo@1234).")
    for _, email, *_ in DOCTORS:
        print(f"  médico:   {email}")
    for _, email in PATIENTS:
        print(f"  paciente: {email}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Popula o banco com dados fictícios.")
    parser.add_argument("--reset", action="store_true", help="apaga todos os dados antes de popular")
    args = parser.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()
