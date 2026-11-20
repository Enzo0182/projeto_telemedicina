"""Estrutura inicial: usuários, sessões, disponibilidade, consultas e prontuário.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    # btree_gist permite combinar igualdade (=) e sobreposição de intervalos (&&) em EXCLUDE.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('paciente', 'medico')", name="ck_users_role"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "doctor_profiles",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("specialty", sa.String(80), nullable=False),
        sa.Column("bio", sa.Text, nullable=False, server_default=""),
        sa.Column("registry", sa.String(40), nullable=False, server_default=""),
    )

    op.create_table(
        "login_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TS, nullable=False),
    )
    op.create_index("ix_login_sessions_token_hash", "login_sessions", ["token_hash"], unique=True)
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])

    op.create_table(
        "availability_periods",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("doctor_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_at", TS, nullable=False),
        sa.Column("end_at", TS, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("end_at > start_at", name="ck_availability_order"),
    )
    op.create_index("ix_availability_periods_doctor_id", "availability_periods", ["doctor_id"])
    op.execute(
        "ALTER TABLE availability_periods ADD CONSTRAINT ex_availability_no_overlap "
        "EXCLUDE USING gist (doctor_id WITH =, tstzrange(start_at, end_at) WITH &&)"
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("doctor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("start_at", TS, nullable=False),
        sa.Column("end_at", TS, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="confirmada"),
        sa.Column("room_code", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.CheckConstraint("end_at > start_at", name="ck_appointment_order"),
        sa.CheckConstraint("status IN ('confirmada', 'cancelada')", name="ck_appointment_status"),
    )
    op.create_index("ix_appointments_doctor_id", "appointments", ["doctor_id"])
    op.create_index("ix_appointments_patient_id", "appointments", ["patient_id"])
    # Garantia final contra consultas sobrepostas, inclusive em requisições simultâneas.
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ex_appointments_doctor_no_overlap "
        "EXCLUDE USING gist (doctor_id WITH =, tstzrange(start_at, end_at) WITH &&) "
        "WHERE (status = 'confirmada')"
    )
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ex_appointments_patient_no_overlap "
        "EXCLUDE USING gist (patient_id WITH =, tstzrange(start_at, end_at) WITH &&) "
        "WHERE (status = 'confirmada')"
    )

    op.create_table(
        "clinical_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("appointment_id", sa.Integer, sa.ForeignKey("appointments.id"), nullable=False, unique=True),
        sa.Column("doctor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("chief_complaint", sa.Text, nullable=False),
        sa.Column("anamnesis", sa.Text, nullable=False, server_default=""),
        sa.Column("assessment", sa.Text, nullable=False, server_default=""),
        sa.Column("conduct", sa.Text, nullable=False, server_default=""),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_clinical_records_doctor_id", "clinical_records", ["doctor_id"])
    op.create_index("ix_clinical_records_patient_id", "clinical_records", ["patient_id"])


def downgrade() -> None:
    op.drop_table("clinical_records")
    op.drop_table("appointments")
    op.drop_table("availability_periods")
    op.drop_table("login_sessions")
    op.drop_table("doctor_profiles")
    op.drop_table("users")
