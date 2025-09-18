from __future__ import annotations

import argparse

from geoprox import user_store


def print_user(user: dict[str, object]) -> None:
    status = "active" if user["is_active"] else "disabled"
    role = "admin" if user["is_admin"] else "user"
    print(f"{user['id']:>3} {user['username']:<16} {role:<5} {status:<8} {user['email'] or '-'}")


def cmd_list(_: argparse.Namespace) -> None:
    users = user_store.list_users(include_disabled=True)
    if not users:
        print("(no users)")
        return
    for user in users:
        print_user(user)


def cmd_add(ns: argparse.Namespace) -> None:
    record = user_store.create_user(
        username=ns.username,
        password=ns.password,
        name=ns.name,
        email=ns.email or "",
        company=ns.company or "",
        company_number=ns.company_number or "",
        phone=ns.phone or "",
        is_admin=ns.admin,
        is_active=not ns.disabled,
    )
    print("Created user:")
    print_user(record)


def cmd_update(ns: argparse.Namespace) -> None:
    user = user_store.get_user_by_username(ns.username)
    if not user:
        raise SystemExit(f"User '{ns.username}' not found")
    updates = {}
    for field in ("name", "email", "company", "company_number", "phone"):
        value = getattr(ns, field)
        if value is not None:
            updates[field] = value
    if ns.admin is not None:
        updates["is_admin"] = ns.admin
    if ns.disabled is not None:
        updates["is_active"] = not ns.disabled
    if updates:
        user_store.update_user(user["id"], **updates)
        print("Updated user")
    else:
        print("Nothing to update")


def cmd_set_password(ns: argparse.Namespace) -> None:
    user = user_store.get_user_by_username(ns.username)
    if not user:
        raise SystemExit(f"User '{ns.username}' not found")
    user_store.set_password(user["id"], ns.password)
    print(f"Password updated for '{ns.username}'")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage GeoProx application users")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Create a new user")
    p_add.add_argument("username")
    p_add.add_argument("password")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--email", default="")
    p_add.add_argument("--company", default="")
    p_add.add_argument("--company-number", dest="company_number", default="")
    p_add.add_argument("--phone", default="")
    p_add.add_argument("--admin", action="store_true")
    p_add.add_argument("--disabled", action="store_true")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List users")
    p_list.set_defaults(func=cmd_list)

    p_update = sub.add_parser("update", help="Update user profile or role")
    p_update.add_argument("username")
    p_update.add_argument("--name")
    p_update.add_argument("--email")
    p_update.add_argument("--company")
    p_update.add_argument("--company-number", dest="company_number")
    p_update.add_argument("--phone")
    p_update.add_argument("--admin", dest="admin", action="store_true")
    p_update.add_argument("--user", dest="admin", action="store_false")
    p_update.add_argument("--disable", dest="disabled", action="store_true")
    p_update.add_argument("--enable", dest="disabled", action="store_false")
    p_update.set_defaults(func=cmd_update, admin=None, disabled=None)

    p_pw = sub.add_parser("set-password", help="Reset a user password")
    p_pw.add_argument("username")
    p_pw.add_argument("password")
    p_pw.set_defaults(func=cmd_set_password)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
