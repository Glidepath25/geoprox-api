from __future__ import annotations

import argparse

from geoprox import user_store


def print_user(user: dict[str, object]) -> None:
    status = "active" if user["is_active"] else "disabled"
    role = "admin" if user["is_admin"] else "user"
    company = user.get("company") or "-"
    company_id = user.get("company_id")
    if company_id:
        company = f"{company} (#{company_id})"
    print(
        f"{user['id']:>3} {user['username']:<16} {role:<5} {status:<8} "
        f"{company:<24} {user['email'] or '-'}"
    )


def print_company(company: dict[str, object]) -> None:
    status = "active" if company["is_active"] else "inactive"
    print(
        f"{company['id']:>3} {company['name']:<24} {status:<8} "
        f"{company['company_number'] or '-':<16} {company['phone'] or '-':<16}"
    )


def cmd_list(ns: argparse.Namespace) -> None:
    users = user_store.list_users(
        include_disabled=ns.include_disabled,
        company_id=ns.company_id,
    )
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
        company_id=ns.company_id,
        is_admin=ns.admin,
        is_active=not ns.disabled,
    )
    print("Created user:")
    print_user(record)


def cmd_update(ns: argparse.Namespace) -> None:
    user = user_store.get_user_by_username(ns.username)
    if not user:
        raise SystemExit(f"User '{ns.username}' not found")
    updates: dict[str, object] = {}
    for field in ("name", "email", "company", "company_number", "phone"):
        value = getattr(ns, field)
        if value is not None:
            updates[field] = value
    if ns.company_id is not None:
        updates["company_id"] = ns.company_id
    if ns.clear_company:
        updates["company_id"] = None
        updates["company"] = ""
    if ns.admin is not None:
        updates["is_admin"] = ns.admin
    if ns.disabled is not None:
        updates["is_active"] = not ns.disabled
    if ns.require_change is not None:
        updates["require_password_change"] = ns.require_change
    if updates:
        user_store.update_user(user["id"], **updates)
        print("Updated user")
    else:
        print("Nothing to update")


def cmd_set_password(ns: argparse.Namespace) -> None:
    user = user_store.get_user_by_username(ns.username)
    if not user:
        raise SystemExit(f"User '{ns.username}' not found")
    user_store.set_password(user["id"], ns.password, require_change=ns.require_change)
    print(f"Password updated for '{ns.username}'")


def cmd_company_list(ns: argparse.Namespace) -> None:
    companies = user_store.list_companies(include_inactive=ns.include_inactive)
    if not companies:
        print("(no companies)")
        return
    for company in companies:
        print_company(company)


def cmd_company_add(ns: argparse.Namespace) -> None:
    record = user_store.create_company(
        name=ns.name,
        company_number=ns.company_number or "",
        phone=ns.phone or "",
        email=ns.email or "",
        notes=ns.notes or "",
    )
    print("Created company:")
    print_company(record)


def cmd_company_update(ns: argparse.Namespace) -> None:
    company = user_store.get_company_by_id(ns.company_id)
    if not company:
        raise SystemExit(f"Company #{ns.company_id} not found")
    updates: dict[str, object] = {}
    for field in ("name", "company_number", "phone", "email", "notes"):
        value = getattr(ns, field)
        if value is not None:
            updates[field] = value
    if ns.inactive:
        updates["is_active"] = False
    if ns.active:
        updates["is_active"] = True
    if updates:
        user_store.update_company(ns.company_id, **updates)
        print("Updated company")
    else:
        print("Nothing to update")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage GeoProx application users and companies")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Create a new user")
    p_add.add_argument("username")
    p_add.add_argument("password")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--email", default="")
    p_add.add_argument("--company", default="")
    p_add.add_argument("--company-id", dest="company_id", type=int)
    p_add.add_argument("--company-number", dest="company_number", default="")
    p_add.add_argument("--phone", default="")
    p_add.add_argument("--admin", action="store_true")
    p_add.add_argument("--disabled", action="store_true")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List users")
    p_list.add_argument("--company-id", dest="company_id", type=int)
    p_list.add_argument("--no-disabled", dest="include_disabled", action="store_false")
    p_list.set_defaults(func=cmd_list, include_disabled=True, company_id=None)

    p_update = sub.add_parser("update", help="Update user profile or role")
    p_update.add_argument("username")
    p_update.add_argument("--name")
    p_update.add_argument("--email")
    p_update.add_argument("--company")
    p_update.add_argument("--company-id", dest="company_id", type=int)
    p_update.add_argument("--clear-company", action="store_true")
    p_update.add_argument("--company-number", dest="company_number")
    p_update.add_argument("--phone")
    p_update.add_argument("--admin", dest="admin", action="store_true")
    p_update.add_argument("--user", dest="admin", action="store_false")
    p_update.add_argument("--disable", dest="disabled", action="store_true")
    p_update.add_argument("--enable", dest="disabled", action="store_false")
    p_update.add_argument("--require-password-change", dest="require_change", action="store_true")
    p_update.add_argument("--no-require-password-change", dest="require_change", action="store_false")
    p_update.set_defaults(func=cmd_update, admin=None, disabled=None, company_id=None, require_change=None)

    p_pw = sub.add_parser("set-password", help="Reset a user password")
    p_pw.add_argument("username")
    p_pw.add_argument("password")
    p_pw.add_argument("--require-change", dest="require_change", action="store_true")
    p_pw.add_argument("--no-require-change", dest="require_change", action="store_false")
    p_pw.set_defaults(func=cmd_set_password, require_change=True)

    p_companies = sub.add_parser("company-list", help="List companies")
    p_companies.add_argument("--include-inactive", action="store_true")
    p_companies.set_defaults(func=cmd_company_list, include_inactive=False)

    p_company_add = sub.add_parser("company-add", help="Create a company")
    p_company_add.add_argument("name")
    p_company_add.add_argument("--company-number", dest="company_number", default="")
    p_company_add.add_argument("--phone", default="")
    p_company_add.add_argument("--email", default="")
    p_company_add.add_argument("--notes", default="")
    p_company_add.set_defaults(func=cmd_company_add)

    p_company_update = sub.add_parser("company-update", help="Update company details")
    p_company_update.add_argument("company_id", type=int)
    p_company_update.add_argument("--name")
    p_company_update.add_argument("--company-number", dest="company_number")
    p_company_update.add_argument("--phone")
    p_company_update.add_argument("--email")
    p_company_update.add_argument("--notes")
    p_company_update.add_argument("--inactive", action="store_true")
    p_company_update.add_argument("--active", action="store_true")
    p_company_update.set_defaults(func=cmd_company_update, inactive=False, active=False)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
