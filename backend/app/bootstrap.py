"""Create the initial branch and administrator without shipping default credentials."""

import argparse
from getpass import getpass

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.setup import lock_admin_provisioning, provision_admin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--location", required=True)
    args = parser.parse_args()
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    password = getpass("Administrator password (12+ characters): ")
    if len(password) < 12 or password != getpass("Confirm password: "):
        parser.error("Passwords must match and contain at least 12 characters")
    with SessionLocal.begin() as db:
        lock_admin_provisioning(db)
        if db.scalar(select(User).where(User.email == email)):
            parser.error("That email already exists; no changes made")
        provision_admin(
            db,
            email=email,
            full_name=args.name,
            branch_name=args.branch,
            location=args.location,
            password=password,
        )
    print("Administrator created.")


if __name__ == "__main__":
    main()
