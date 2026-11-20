"""Admin tasks you run from the terminal (the first admin can't be created through the API).

Run it inside the api container:

    docker compose exec api python -m app.manage set-tier ama@mail.com admin

Tiers: free, premium, admin. is_premium follows the tier automatically.
"""

import argparse
import sys

from app.database import SessionLocal
from app.models import TIERS
from app.repositories import UserRepository


def set_tier(email: str, tier: str) -> None:
    with SessionLocal() as db:
        users = UserRepository(db)
        user = users.get_by_email(email.lower())
        if user is None:
            print(f"No user with the email {email}")
            sys.exit(1)

        users.update(user, {"tier": tier})
        print(f"{user.email} is now '{user.tier}' (is_premium={user.is_premium})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Admin tasks for the URL shortener")
    commands = parser.add_subparsers(dest="command", required=True)

    set_tier_command = commands.add_parser("set-tier", help="change a user's tier")
    set_tier_command.add_argument("email")
    set_tier_command.add_argument("tier", choices=TIERS)

    arguments = parser.parse_args()
    if arguments.command == "set-tier":
        set_tier(arguments.email, arguments.tier)


if __name__ == "__main__":
    main()
