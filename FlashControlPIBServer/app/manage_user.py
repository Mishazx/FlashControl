import argparse
import getpass

from .auth import ALLOWED_ROLES, create_local_user
from .db import SessionLocal, initialize_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage FlashControl local DEV users")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="Create a local user")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=ALLOWED_ROLES, default="admin")
    create.add_argument("--password", help="Non-interactive password (minimum 12 characters)")
    args = parser.parse_args()

    initialize_database()
    if args.password:
        password = args.password
    else:
        password = getpass.getpass("Password (minimum 12 characters): ")
        confirmation = getpass.getpass("Repeat password: ")
        if password != confirmation:
            parser.error("passwords do not match")
    with SessionLocal() as db:
        user = create_local_user(db, args.username, password, args.role)
    print("Created local user %s with role %s" % (user.username, user.role))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
