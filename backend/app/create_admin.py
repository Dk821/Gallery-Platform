"""
Usage:
    python -m app.create_admin

Prompts for name / email / password and creates the first (or an additional)
admin account. Password is hashed with Argon2 before it ever touches the DB.
"""

import getpass
import sys

from app.database.connection import SessionLocal
from app.models.admin import Admin
from app.security.password import hash_password


def main() -> None:
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()
    password = getpass.getpass("Admin password: ")
    confirm = getpass.getpass("Confirm password: ")

    if not name or not email:
        print("Name and email are required.")
        sys.exit(1)
    if len(password) != 8:
        print("Password must be exactly 8 characters.")
        sys.exit(1)
    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = db.query(Admin).filter(Admin.email == email).first()
        if existing:
            print(f"An admin with email {email} already exists.")
            sys.exit(1)

        admin = Admin(name=name, email=email, password_hash=hash_password(password), status="active")
        db.add(admin)
        db.commit()
        print(f"Admin '{name}' <{email}> created successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
