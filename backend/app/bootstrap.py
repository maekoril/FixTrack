"""Create the initial branch and administrator without shipping default credentials."""

import argparse
from getpass import getpass

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Branch, BranchAccess, Role, User
from app.security import password_hash


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
        if db.scalar(select(User).where(User.email == email)):
            parser.error("That email already exists; no changes made")
        branch = db.scalar(select(Branch).where(Branch.name == args.branch))
        if branch is None:
            branch = Branch(name=args.branch, location=args.location)
            db.add(branch)
            db.flush()
        user = User(
            email=email,
            full_name=args.name,
            role=Role.administrator,
            password_hash=password_hash.hash(password),
        )
        db.add(user)
        db.flush()
        db.add(BranchAccess(user_id=user.id, branch_id=branch.id))
    print("Administrator created.")


if __name__ == "__main__":
    main()
