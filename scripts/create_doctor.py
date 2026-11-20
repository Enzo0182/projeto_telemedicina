"""Função administrativa de demonstração: cria uma conta de médico (fictícia).

Uso:
    python -m scripts.create_doctor --name "Dra. Fulana" --email fulana@medico.example \
        --specialty "Neurologia" [--bio "..."] [--registry "CRM-FICT 123"]

A senha é solicitada de forma interativa (não aparece no terminal nem em logs).
"""
import argparse
import getpass
import sys

from app.database import SessionLocal
from app.errors import Conflict
from app.schemas import EMAIL_RE
from app.services.users import create_doctor


def main() -> None:
    p = argparse.ArgumentParser(description="Cria uma conta de médico fictícia.")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--specialty", required=True)
    p.add_argument("--bio", default="Perfil fictício para demonstração.")
    p.add_argument("--registry", default="CRM-FICT")
    args = p.parse_args()

    if not EMAIL_RE.match(args.email.strip()):
        sys.exit("E-mail inválido.")
    password = getpass.getpass("Senha do médico (mín. 8 caracteres): ")
    if len(password) < 8 or password != getpass.getpass("Confirme a senha: "):
        sys.exit("Senha inválida ou não confirmada.")
    with SessionLocal() as db:
        try:
            user = create_doctor(db, name=args.name.strip(), email=args.email, password=password,
                                 specialty=args.specialty.strip(), bio=args.bio, registry=args.registry)
        except Conflict as exc:
            sys.exit(exc.message)
    print(f"Médico criado: {user.name} <{user.email}> (id {user.id})")


if __name__ == "__main__":
    main()
