import argparse
import sys
from app.core.database import SessionLocal
from app.services.tutor_provision import provision_tutor
from app.services.academic_service import seed_default_academic_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Valhalla Tutor CLI Administration")
    subparsers = parser.add_subparsers(dest="command")

    tutor_parser = subparsers.add_parser("create-tutor", help="Provision tutor account")
    tutor_parser.add_argument("--username", required=True, help="Tutor username")
    tutor_parser.add_argument("--password", required=True, help="Tutor password")
    tutor_parser.add_argument("--name", default="Valhalla Tutor", help="Full name")
    tutor_parser.add_argument("--email", default=None, help="Tutor email (optional)")
    tutor_parser.add_argument("--timezone", default="Asia/Tehran", help="User timezone")

    subparsers.add_parser("seed-academic", help="Seed default academic tracks and subjects")

    args = parser.parse_args()
    if args.command == "create-tutor":
        db = SessionLocal()
        try:
            tutor = provision_tutor(
                db=db,
                username=args.username,
                password=args.password,
                full_name=args.name,
                email=args.email,
                timezone=args.timezone,
            )
            print(f"Tutor account '{tutor.username}' provisioned successfully (ID: {tutor.id}).")
        finally:
            db.close()
    elif args.command == "seed-academic":
        db = SessionLocal()
        try:
            seed_default_academic_data(db)
            print("Default academic tracks ('ریاضی', 'تجربی') and subjects seeded successfully.")
        finally:
            db.close()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

