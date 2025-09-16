from __future__ import annotations

import argparse
import json
from pathlib import Path

from geoprox.auth import USERS_DIR, create_user_record


def ensure_users_dir() -> Path:
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    return USERS_DIR


def add_user(username: str, password: str, *, overwrite: bool = False) -> Path:
    ensure_users_dir()
    path = USERS_DIR / f"{username}.json"
    if path.exists() and not overwrite:
        raise SystemExit(f"User '{username}' already exists. Use --overwrite to replace.")
    record = create_user_record(username, password)
    path.write_text(json.dumps(record, indent=2))
    return path


def delete_user(username: str) -> None:
    path = USERS_DIR / f"{username}.json"
    if not path.exists():
        raise SystemExit(f"User '{username}' not found")
    path.unlink()


def list_users() -> None:
    if not USERS_DIR.exists():
        print("(no users configured)")
        return
    for path in sorted(USERS_DIR.glob("*.json")):
        print(path.stem)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage GeoProx basic-auth users")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Add or update a user")
    p_add.add_argument("username")
    p_add.add_argument("password")
    p_add.add_argument("--overwrite", action="store_true", help="Replace existing user")

    p_del = sub.add_parser("delete", help="Delete a user")
    p_del.add_argument("username")

    sub.add_parser("list", help="List users")

    args = parser.parse_args(argv)

    if args.command == "add":
        path = add_user(args.username, args.password, overwrite=args.overwrite)
        print(f"Saved credentials for '{args.username}' to {path}")
    elif args.command == "delete":
        delete_user(args.username)
        print(f"Deleted user '{args.username}'")
    elif args.command == "list":
        list_users()


if __name__ == "__main__":
    main()