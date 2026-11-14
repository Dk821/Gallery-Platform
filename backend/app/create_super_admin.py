"""
Usage:
    python -m app.create_super_admin

Creates a platform super admin (no studio). Prompts for name / email /
password; the password is hashed with Argon2 before it touches the database
and is never printed or logged. Minimum 4 characters.
"""

import getpass
import sys

from app.database.connection import SessionLocal
from app.models.admin import Admin
from app.security.password import hash_password

MIN_LENGTH = 4


def main() -> None:
    name = input("Super admin name: ").strip()
    email = input("Super admin email: ").strip().lower()
    password = getpass.getpass("Password (min 4 characters): ")
    confirm = getpass.getpass("Confirm password: ")

    if not name or not email:
        print("Name and email are required.")
        sys.exit(1)
    if len(password) < MIN_LENGTH:
        print(f"Password must be at least {MIN_LENGTH} characters.")
        sys.exit(1)
    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)

    db = SessionLocal()
    try:
        if db.query(Admin).filter(Admin.email == email).first():
            print(f"An admin with email {email} already exists.")
            sys.exit(1)
        db.add(
            Admin(
                name=name,
                email=email,
                password_hash=hash_password(password),
                status="active",
                role="super_admin",
                studio_id=None,
            )
        )
        db.commit()
        print(f"Super admin '{name}' <{email}> created.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
