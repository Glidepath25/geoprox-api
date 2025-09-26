# geoprox/main.py
from __future__ import annotations

import os
import logging
import sqlite3
import csv
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field

from geoprox import history_store, user_store, permit_store
from geoprox.core import run_geoprox_search
log = logging.getLogger("uvicorn.error")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[1]
STATIC_DIR = (REPO_ROOT / "static").resolve()
TEMPLATES_DIR = (REPO_ROOT / "templates").resolve()
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "artifacts")).resolve()
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

PROMO_PDF_URL = os.environ.get("LOGIN_PROMO_PDF", "/static/geoprox-intro.pdf")
SUPPORT_EMAIL = os.environ.get("GEOPROX_SUPPORT_EMAIL", "useradmin@geoprox.co.uk")

DEFAULT_W3W_KEY = "OXT6XQ19"

# Ensure templates directory exists
if not TEMPLATES_DIR.exists():
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    log.warning("templates/ directory was missing; created at %s", TEMPLATES_DIR)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="GeoProx API", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_SECRET = os.environ.get("SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = "dev-secret-key"
    log.warning("SESSION_SECRET not set; using insecure default. Set SESSION_SECRET in production.")

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="strict")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# only mount /static (not as root) for assets like logo/index
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    log.info(f"Static dir: {STATIC_DIR}")
else:
    log.warning(f"static/ not found at {STATIC_DIR}")

if user_store.USE_POSTGRES:
    log.info("Database backend: Postgres host=%s db=%s user=%s", os.environ.get("DB_HOST"), os.environ.get("DB_NAME"), os.environ.get("DB_USER"))
else:
    log.warning("Database backend: SQLite fallback at %s (DB_HOST unset). Set DB_* secrets to use Aurora.", user_store.DB_PATH)

def _bootstrap_admin_from_env() -> None:
    username = (os.environ.get("BOOTSTRAP_ADMIN_USERNAME") or "").strip()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
    if not username or not password:
        return
    email = (os.environ.get("BOOTSTRAP_ADMIN_EMAIL") or "").strip()
    display_name = (os.environ.get("BOOTSTRAP_ADMIN_NAME") or username or "GeoProx Admin").strip()
    company = (os.environ.get("BOOTSTRAP_ADMIN_COMPANY") or "GeoProx").strip()
    try:
        user = user_store.get_user_by_username(username)
        if user:
            user_store.set_password(user["id"], password, require_change=False)
            updates: Dict[str, Any] = {}
            if not user.get("is_admin"):
                updates["is_admin"] = True
            if not user.get("is_active"):
                updates["is_active"] = True
            if email and (user.get("email") or "") != email:
                updates["email"] = email
            if company and (user.get("company") or "") != company:
                updates["company"] = company
            if updates:
                user_store.update_user(user["id"], **updates)
            log.warning("Bootstrap admin reset for '%s'. Remove BOOTSTRAP_ADMIN_* env vars after use.", username)
        else:
            user_store.create_user(
                username=username,
                password=password,
                name=display_name,
                email=email,
                company=company,
                company_number="",
                phone="",
                company_id=None,
                is_admin=True,
                is_active=True,
                require_password_change=False,
                license_tier="pro",
            )
            log.warning("Bootstrap admin created for '%s'. Remove BOOTSTRAP_ADMIN_* env vars after use.", username)
    except Exception:
        log.exception("Bootstrap admin routine failed for '%s'.", username)


@app.on_event("startup")
async def _on_startup() -> None:
    _bootstrap_admin_from_env()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalise_location(s: str) -> str:
    """Normalise/validate location string."""
    if not s:
        raise HTTPException(status_code=400, detail="Location is required.")
    s = s.strip()
    if s.startswith("///"):
        return s

    try:
        parts = s.replace(" ", "").split(",")
        if len(parts) != 2:
            raise ValueError("Need two comma-separated numbers.")
        lat = float(parts[0])
        lon = float(parts[1])
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ValueError("Lat/lon out of range.")
        return f"{lat},{lon}"
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid location. Use 'lat,lon' (e.g. '54.35,-6.65') or a '///what.three.words' address.",
        )



def _validate_polygon_coords(raw: List[List[float]]) -> Tuple[List[Tuple[float, float]], Tuple[float, float]]:
    if not raw or len(raw) < 3:
        raise HTTPException(status_code=400, detail="Polygon must contain at least three vertices.")
    cleaned: List[Tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise HTTPException(status_code=400, detail="Polygon vertices must be [lat, lon].")
        try:
            lat = float(point[0])
            lon = float(point[1])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Polygon vertices must be numeric lat/lon values.")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise HTTPException(status_code=400, detail="Polygon vertices must be valid lat/lon values.")
        cleaned.append((lat, lon))
    twice_area = 0.0
    cx = 0.0
    cy = 0.0
    for idx, (lat1, lon1) in enumerate(cleaned):
        lat2, lon2 = cleaned[(idx + 1) % len(cleaned)]
        x1, y1 = lon1, lat1
        x2, y2 = lon2, lat2
        cross = x1 * y2 - x2 * y1
        twice_area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(twice_area) < 1e-9:
        avg_lat = sum(lat for lat, _ in cleaned) / len(cleaned)
        avg_lon = sum(lon for _, lon in cleaned) / len(cleaned)
        centroid = (avg_lat, avg_lon)
    else:
        area = twice_area * 0.5
        centroid = (cy / (6.0 * area), cx / (6.0 * area))
    return cleaned, centroid



def _load_w3w_key() -> Optional[str]:
    key = (os.environ.get("WHAT3WORDS_API_KEY") or "").strip()
    if key:
        return key
    key_file = (REPO_ROOT / "config" / "what3words_key.txt")
    if key_file.exists():
        try:
            key = key_file.read_text(encoding="utf-8").strip()
        except Exception:
            key = ""
        if key:
            return key
    if DEFAULT_W3W_KEY:
        return DEFAULT_W3W_KEY
    return None


def _safe_artifact(path: str, request: Request) -> Path:
    _require_user(request)
    full = (ARTIFACTS_DIR / path).resolve()
    if not str(full).startswith(str(ARTIFACTS_DIR)):
        log.warning("artifact blocked path=%s base=%s", full, ARTIFACTS_DIR)
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not full.exists():
        available = []
        try:
            available = sorted(p.name for p in ARTIFACTS_DIR.glob('*'))[:20]
        except Exception:
            available = []
        log.warning("artifact missing path=%s base=%s available=%s", full, ARTIFACTS_DIR, available)
        raise HTTPException(status_code=404, detail="Not Found")
    return full


def _require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _require_admin(request: Request) -> str:
    user = _require_user(request)
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def _start_session_for_user(request: Request, user: Dict[str, Any]) -> None:
    request.session.clear()
    request.session["user"] = user["username"]
    request.session["user_id"] = user["id"]
    request.session["is_admin"] = bool(user["is_admin"])
    request.session["display_name"] = user["name"]
    history_rows = history_store.get_history(user["username"], limit=5)
    session_history = []
    for row in reversed(history_rows):
        session_history.append({
            "timestamp": row["timestamp"],
            "location": (row.get("location") or "")[:80],
            "radius_m": int(row.get("radius_m", 0)),
            "outcome": row.get("outcome"),
            "permit": row.get("permit"),
            "mode": "point",
        })
    request.session["history"] = session_history


def _render_login(
    request: Request,
    *,
    status: int = 200,
    login_error: Optional[str] = None,
    username: str = "",
    signup_error: Optional[str] = None,
    signup_success: Optional[str] = None,
    signup_data: Optional[Dict[str, str]] = None,
    upgrade_error: Optional[str] = None,
    upgrade_success: Optional[str] = None,
    upgrade_data: Optional[Dict[str, str]] = None,
    open_modal: Optional[str] = None,
) -> HTMLResponse:
    upgrade_options = [
        (key, meta["label"])
        for key, meta in user_store.LICENSE_TIERS.items()
        if key != "free_trial"
    ]
    context = {
        "request": request,
        "error": login_error,
        "username": username,
        "signup_error": signup_error,
        "signup_success": signup_success,
        "signup_data": signup_data or {},
        "upgrade_error": upgrade_error,
        "upgrade_success": upgrade_success,
        "upgrade_data": upgrade_data or {},
        "open_modal": open_modal or "",
        "promo_pdf_url": PROMO_PDF_URL,
        "upgrade_options": upgrade_options,
    }
    return templates.TemplateResponse("login.html", context, status_code=status)



def _send_upgrade_email(
    *,
    name: str,
    email: str,
    company: str,
    current_tier: str,
    desired_tier: str,
    notes: str,
) -> bool:
    host = os.environ.get("SMTP_HOST")
    if not host:
        log.warning("SMTP_HOST not configured; unable to send upgrade enquiry email")
        return False
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError:
        port = 587
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() not in {"false", "0", "no"}
    from_address = os.environ.get("SMTP_FROM") or username or SUPPORT_EMAIL

    message = EmailMessage()
    message["Subject"] = "new user enquiry"
    message["From"] = from_address
    message["To"] = SUPPORT_EMAIL
    if email:
        message["Reply-To"] = email
    body = (
        "New GeoProx upgrade enquiry\n\n"
        f"Name: {name or 'N/A'}\n"
        f"Email: {email or 'N/A'}\n"
        f"Company: {company or 'N/A'}\n"
        f"Current tier: {current_tier or 'Free Trial'}\n"
        f"Requested tier: {desired_tier or 'N/A'}\n\n"
        "Additional information:\n"
        f"{notes or 'N/A'}\n"
    )
    message.set_content(body)

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls(context=context)
                if username and password:
                    server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                if username and password:
                    server.login(username, password)
                server.send_message(message)
    except Exception:
        log.exception("Failed to send upgrade enquiry email")
        return False
    return True


def _parse_optional_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except (TypeError, ValueError):
        return None



def _ensure_can_change_admin_flag(request: Request, user: Dict[str, Any], new_is_admin: bool) -> None:
    current_user_id = request.session.get("user_id")
    if user["id"] == current_user_id and not new_is_admin:
        raise HTTPException(status_code=400, detail="You cannot remove administrator rights from your own account.")
    if user["is_admin"] and not new_is_admin:
        others = [u for u in user_store.list_users(include_disabled=False) if u["is_admin"] and u["id"] != user["id"]]
        if not others:
            raise HTTPException(status_code=400, detail="At least one active administrator is required.")


def _ensure_can_change_active_status(
    request: Request,
    user: Dict[str, Any],
    *,
    enable: bool,
    target_is_admin: Optional[bool] = None,
) -> None:
    is_admin = user["is_admin"] if target_is_admin is None else bool(target_is_admin)
    current_user_id = request.session.get("user_id")
    if user["id"] == current_user_id and not enable:
        raise HTTPException(status_code=400, detail="You cannot disable your own account.")
    if not enable and is_admin:
        others = [u for u in user_store.list_users(include_disabled=False) if u["is_admin"] and u["id"] != user["id"]]
        if not others:
            raise HTTPException(status_code=400, detail="At least one active administrator is required.")

def _add_flash(request: Request, message: str, category: str = "info") -> None:
    flashes = request.session.get("_flashes") or []
    flashes.append({"message": message, "category": category})
    request.session["_flashes"] = flashes


def _redirect_admin_users(company_id: Optional[int] = None) -> RedirectResponse:
    url = "/admin/users"
    if company_id:
        url = f"{url}?company_id={company_id}"
    return RedirectResponse(url=url, status_code=303)


def _consume_flashes(request: Request) -> List[Dict[str, str]]:
    flashes = request.session.get("_flashes") or []
    if flashes:
        request.session["_flashes"] = []
    return flashes


def _user_to_out(
    user: Dict[str, Any],
    counts: Optional[Dict[str, int]] = None,
    monthly_counts: Optional[Dict[str, int]] = None,
) -> AdminUserOut:
    search_counts = counts or {}
    monthly = monthly_counts or {}
    raw_tier = user.get("license_tier") or user_store.DEFAULT_LICENSE_TIER
    try:
        normalized_tier = user_store.normalize_license_tier(raw_tier)
    except ValueError:
        normalized_tier = user_store.DEFAULT_LICENSE_TIER
    monthly_limit = user_store.get_license_monthly_limit(normalized_tier)
    monthly_used = int(monthly.get(user["username"], 0))
    tier_label = user_store.LICENSE_TIERS[normalized_tier]["label"]
    return AdminUserOut(
        id=user["id"],
        username=user["username"],
        name=user["name"],
        email=user["email"] or "",
        company=user["company"] or "",
        company_id=user.get("company_id"),
        company_number=user["company_number"] or "",
        phone=user["phone"] or "",
        is_admin=bool(user["is_admin"]),
        is_active=bool(user["is_active"]),
        require_password_change=bool(user.get("require_password_change")),
        license_tier=normalized_tier,
        license_label=tier_label,
        monthly_search_limit=monthly_limit,
        monthly_search_count=monthly_used,
        search_count=int(search_counts.get(user["username"], 0)),
        created_at=user["created_at"],
        updated_at=user["updated_at"],
    )

def _company_to_out(company: Dict[str, Any]) -> AdminCompanyOut:
    return AdminCompanyOut(
        id=company["id"],
        name=company["name"],
        company_number=company["company_number"] or "",
        phone=company["phone"] or "",
        email=company["email"] or "",
        notes=company["notes"] or "",
        is_active=bool(company["is_active"]),
        created_at=company["created_at"],
        updated_at=company["updated_at"],
    )

def _permit_to_response(record: Dict[str, Any]) -> PermitRecordResp:
    location = record.get("location") or {}
    desktop = record.get("desktop") or {}
    site = record.get("site") or {}

    desktop_summary = desktop.get("summary") if isinstance(desktop.get("summary"), dict) else None
    site_payload = site.get("payload") if isinstance(site.get("payload"), dict) else None
    search_payload = record.get("search_result") if isinstance(record.get("search_result"), dict) else None
    desktop_notes = desktop.get("notes") if isinstance(desktop.get("notes"), str) else None
    site_notes = site.get("notes") if isinstance(site.get("notes"), str) else None

    return PermitRecordResp(
        permit_ref=str(record.get("permit_ref", "")),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        location=PermitLocation(
            display=location.get("display"),
            lat=location.get("lat"),
            lon=location.get("lon"),
            radius_m=location.get("radius_m"),
        ),
        desktop=PermitStage(
            status=str(desktop.get("status") or "Pending"),
            outcome=desktop.get("outcome"),
            notes=desktop_notes,
            summary=desktop_summary,
        ),
        site=PermitStage(
            status=str(site.get("status") or "Not started"),
            outcome=site.get("outcome"),
            notes=site_notes,
            payload=site_payload,
        ),
        search_result=search_payload,
    )



# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if request.session.get("user"):
        return RedirectResponse(url="/dashboard", status_code=303)
    return _render_login(request)


@app.post("/login", response_class=HTMLResponse)
async def login_action(request: Request, username: str = Form(...), password: str = Form(...)) -> HTMLResponse:
    username = username.strip()
    if '@' in username:
        username = username.lower()
    user = user_store.verify_credentials(username, password, include_disabled=True)
    if user and not user["is_active"]:
        error = "Account disabled. Please contact your administrator."
    elif user:
        if user.get("require_password_change"):
            request.session.clear()
            request.session["pending_user_id"] = user["id"]
            request.session["pending_username"] = username
            log.info("User %s must change password on next login", username)
            return RedirectResponse(url="/change-password", status_code=303)
        _start_session_for_user(request, user)
        log.info("User %s logged in", username)
        return RedirectResponse(url="/dashboard", status_code=303)
    else:
        error = "Invalid username or password."
    return _render_login(request, status=401, login_error=error, username=username)


@app.post("/signup/free-trial", response_class=HTMLResponse)
async def signup_free_trial(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    company_name: str = Form(...),
    company_number: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
) -> Response:
    data = {
        "full_name": full_name.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "company_name": company_name.strip(),
        "company_number": company_number.strip(),
    }

    def render_error(message: str, *, status: int = 400) -> HTMLResponse:
        return _render_login(
            request,
            status=status,
            signup_error=message,
            signup_data=data,
            open_modal="signup",
        )

    email_clean = data["email"].strip().lower()
    if not email_clean:
        return render_error("Email address is required.")
    username = email_clean
    if user_store.get_user_by_username(username):
        return render_error("An account with that email already exists.")
    if len(password) < 8:
        return render_error("Password must be at least 8 characters long.")
    if password != confirm_password:
        return render_error("Passwords do not match.")

    try:
        user_store.create_user(
            username=username,
            password=password,
            name=data["full_name"],
            email=data["email"],
            phone=data["phone"],
            company=data["company_name"],
            company_number=data["company_number"],
            company_id=None,
            is_admin=False,
            is_active=True,
            require_password_change=False,
            license_tier="free_trial",
        )
    except sqlite3.IntegrityError:
        return render_error("An account with that email already exists.")
    except ValueError as exc:
        return render_error(str(exc) or "Unable to create account with the provided details.")

    user_record = user_store.get_user_by_username(username)
    if not user_record:
        return render_error("Something went wrong creating your account. Please try again.")

    _start_session_for_user(request, user_record)
    log.info("Created free trial account for %s", username)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/request-upgrade", response_class=HTMLResponse)
async def request_upgrade(
    request: Request,
    contact_name: str = Form(...),
    contact_email: str = Form(...),
    company: str = Form(""),
    current_tier: str = Form("Free Trial"),
    desired_tier: str = Form(...),
    notes: str = Form(""),
) -> HTMLResponse:
    data = {
        "contact_name": contact_name.strip(),
        "contact_email": contact_email.strip(),
        "company": company.strip(),
        "current_tier": current_tier.strip() or "Free Trial",
        "desired_tier": desired_tier.strip().lower(),
        "notes": notes.strip(),
    }

    if not data["desired_tier"]:
        return _render_login(
            request,
            status=400,
            upgrade_error="Please select the licence tier you're interested in.",
            upgrade_data=data,
            open_modal="upgrade",
        )

    if data["desired_tier"] not in user_store.LICENSE_TIERS:
        return _render_login(
            request,
            status=400,
            upgrade_error="Please choose a valid licence tier option.",
            upgrade_data=data,
            open_modal="upgrade",
        )

    sent = _send_upgrade_email(
        name=data["contact_name"],
        email=data["contact_email"],
        company=data["company"],
        current_tier=data["current_tier"],
        desired_tier=user_store.LICENSE_TIERS[data["desired_tier"]]["label"],
        notes=data["notes"],
    )
    if not sent:
        return _render_login(
            request,
            status=500,
            upgrade_error="We couldn't send your enquiry right now. Please email useradmin@geoprox.co.uk instead.",
            upgrade_data=data,
            open_modal="upgrade",
        )

    log.info("Upgrade enquiry submitted for %s (%s)", data["contact_name"], data["contact_email"])
    return _render_login(
        request,
        upgrade_success="Thanks! We've received your enquiry and will be in touch soon.",
    )


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)



@app.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request) -> HTMLResponse:
    pending_user_id = request.session.get("pending_user_id")
    current_username = request.session.get("user")
    if not pending_user_id and not current_username:
        return RedirectResponse(url="/", status_code=303)
    username = request.session.get("pending_username") or current_username
    return templates.TemplateResponse(
        "change_password.html",
        {"request": request, "username": username or "", "error": None, "success": False},
    )


@app.post("/change-password", response_class=HTMLResponse)
async def change_password_action(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> HTMLResponse:
    pending_user_id = request.session.get("pending_user_id")
    current_user_id = request.session.get("user_id")
    if not pending_user_id and not current_user_id:
        return RedirectResponse(url="/", status_code=303)
    user_id = pending_user_id or current_user_id
    user_record = user_store.get_user_by_id(int(user_id))
    if not user_record:
        request.session.clear()
        return RedirectResponse(url="/", status_code=303)
    username = user_record["username"]
    if new_password != confirm_password:
        error = "Passwords do not match."
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "username": username, "error": error, "success": False},
            status_code=400,
        )
    if len(new_password) < 8:
        error = "Password must be at least 8 characters long."
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "username": username, "error": error, "success": False},
            status_code=400,
        )
    if user_store.verify_credentials(username, current_password, include_disabled=True) is None:
        error = "Current password is incorrect."
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "username": username, "error": error, "success": False},
            status_code=400,
        )
    user_store.set_password(user_record["id"], new_password, require_change=False)
    updated = user_store.get_user_by_id(user_record["id"])
    if not updated:
        request.session.clear()
        return RedirectResponse(url="/", status_code=303)
    _start_session_for_user(request, updated)
    log.info("User %s changed password", username)
    request.session.pop("pending_user_id", None)
    request.session.pop("pending_username", None)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request) -> HTMLResponse:
    if request.session.get("user"):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        "forgot_password.html",
        {"request": request, "error": None, "username": "", "company_number": "", "email": ""},
    )


@app.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_action(
    request: Request,
    username: str = Form(...),
    company_number: str = Form(...),
    email: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> HTMLResponse:
    user = user_store.get_user_by_username(username.strip())
    if not user:
        error = "Account not found."
    elif not user["is_active"]:
        error = "Account is disabled."
    elif new_password != confirm_password:
        error = "Passwords do not match."
    elif len(new_password) < 8:
        error = "Password must be at least 8 characters long."
    else:
        stored_company_number = (user.get("company_number") or "").strip()
        if stored_company_number and stored_company_number.lower() != company_number.strip().lower():
            error = "Company number does not match our records."
        else:
            stored_email = (user.get("email") or "").strip()
            if stored_email and stored_email.lower() != email.strip().lower():
                error = "Email does not match our records."
            else:
                user_store.set_password(user["id"], new_password, require_change=False)
                updated = user_store.get_user_by_id(user["id"])
                if updated:
                    _start_session_for_user(request, updated)
                    log.info("User %s reset password via self-service", username)
                    return RedirectResponse(url="/dashboard", status_code=303)
                error = "Unable to update password. Please contact support."
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "error": error,
            "username": username,
            "company_number": company_number,
            "email": email,
        },
        status_code=400,
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AdminUserOut(BaseModel):
    id: int
    username: str
    name: str
    email: str
    company: str
    company_id: Optional[int]
    company_number: str
    phone: str
    is_admin: bool
    is_active: bool
    require_password_change: bool
    license_tier: str
    license_label: str
    monthly_search_limit: Optional[int]
    monthly_search_count: int
    search_count: int
    created_at: str
    updated_at: str


class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=128)
    email: Optional[str] = Field(default="", max_length=256)
    company: Optional[str] = Field(default="", max_length=256)
    company_id: Optional[int] = None
    company_number: Optional[str] = Field(default="", max_length=64)
    phone: Optional[str] = Field(default="", max_length=64)
    is_admin: bool = False
    is_active: bool = True
    require_password_change: bool = True
    license_tier: str = Field(default=user_store.DEFAULT_LICENSE_TIER)


class AdminUserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    email: Optional[str] = Field(default=None, max_length=256)
    company: Optional[str] = Field(default=None, max_length=256)
    company_id: Optional[int] = None
    company_number: Optional[str] = Field(default=None, max_length=64)
    phone: Optional[str] = Field(default=None, max_length=64)
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    require_password_change: Optional[bool] = None
    license_tier: Optional[str] = None


class AdminPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class AdminActionResult(BaseModel):
    status: str = "ok"
    message: Optional[str] = None


class AdminCompanyOut(BaseModel):
    id: int
    name: str
    company_number: str
    phone: str
    email: str
    notes: str
    is_active: bool
    created_at: str
    updated_at: str


class AdminCompanyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    company_number: Optional[str] = Field(default="", max_length=128)
    phone: Optional[str] = Field(default="", max_length=64)
    email: Optional[str] = Field(default="", max_length=256)
    notes: Optional[str] = Field(default="", max_length=1024)
    is_active: bool = True


class AdminCompanyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=256)
    company_number: Optional[str] = Field(default=None, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=256)
    notes: Optional[str] = Field(default=None, max_length=1024)
    is_active: Optional[bool] = None



class PermitStage(BaseModel):
    status: str
    outcome: Optional[str] = None
    notes: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    payload: Optional[Dict[str, Any]] = None

    class Config:
        extra = "forbid"


class PermitLocation(BaseModel):
    display: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_m: Optional[int] = None

    class Config:
        extra = "forbid"


class PermitRecordResp(BaseModel):
    permit_ref: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    location: PermitLocation
    desktop: PermitStage
    site: PermitStage
    search_result: Optional[Dict[str, Any]] = None

    class Config:
        extra = "forbid"


class PermitSaveReq(BaseModel):
    permit_ref: str = Field(..., min_length=1, max_length=120)
    result: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "forbid"


class PermitSiteUpdateReq(BaseModel):
    status: str = Field(default="Completed", min_length=1, max_length=120)
    outcome: Optional[str] = None
    notes: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

    class Config:
        extra = "forbid"

class SearchReq(BaseModel):
    location: str = Field(..., description="lat,lon or ///what.three.words")
    radius_m: int = Field(..., ge=10, le=20000, examples=[2000])
    categories: List[str] = Field(default_factory=list)
    permit: Optional[str] = None
    max_results: Optional[int] = Field(default=None, ge=1, le=10000)
    selection_mode: str = Field(default="point", description="Search selection mode (point or polygon)")
    polygon: Optional[List[List[float]]] = Field(default=None, description="Polygon vertices as [lat, lon] pairs")


class SearchResp(BaseModel):
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    debug: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz() -> Dict[str, bool]:
    return {"ok": True}


@app.get("/auth-status")
def auth_status(request: Request):
    if request.session.get("user"):
        return {"authenticated": True}
    raise HTTPException(status_code=401, detail="Authentication required")


@app.get("/api/history")
def api_history(request: Request):
    username = _require_user(request)
    items = history_store.get_history(username, limit=20)
    return {"history": items}



@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "display_name": request.session.get("display_name") or user,
        },
    )


@app.get("/permits", response_class=HTMLResponse)
async def permits_page(request: Request) -> HTMLResponse:
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "permits.html",
        {
            "request": request,
            "user": user,
            "display_name": request.session.get("display_name") or user,
        },
    )

@app.get("/app")
async def app_page(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/", status_code=303)
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse({"status": "ok"})
    return FileResponse(str(index_file), media_type="text/html")


@app.get("/artifacts/{path:path}")
def get_artifact(request: Request, path: str):
    full = _safe_artifact(path, request)
    suffix = full.suffix.lower()
    if suffix == ".html":
        media = "text/html"
    elif suffix == ".pdf":
        media = "application/pdf"
    elif suffix == ".js":
        media = "application/javascript"
    elif suffix == ".css":
        media = "text/css"
    else:
        media = None
    return FileResponse(str(full), media_type=media)



@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request) -> HTMLResponse:
    user = _require_user(request)
    items = history_store.get_history(user, limit=200)
    return templates.TemplateResponse("history.html", {
        "request": request,
        "user": user,
        "items": items,
        "is_admin": bool(request.session.get("is_admin")),
    })

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, company_id: Optional[int] = None) -> HTMLResponse:
    _require_admin(request)
    companies = user_store.list_companies(include_inactive=False)
    users = user_store.list_users(include_disabled=True, company_id=company_id)
    search_counts = history_store.get_user_search_counts()
    monthly_counts = history_store.get_user_monthly_search_counts()
    flashes = _consume_flashes(request)
    return templates.TemplateResponse(
        "admin_users.html",
        {
            "request": request,
            "users": users,
            "companies": companies,
            "selected_company": company_id,
            "flashes": flashes,
            "current_user": request.session.get("user"),
            "search_counts": search_counts,
            "monthly_counts": monthly_counts,
            "license_tiers": user_store.LICENSE_TIERS,
        },
    )


@app.get("/admin/users/export.csv")
async def admin_export_users(request: Request) -> Response:
    _require_admin(request)
    users = user_store.list_users(include_disabled=True)
    counts = history_store.get_user_search_counts()
    monthly_counts = history_store.get_user_monthly_search_counts()
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Username", "Name", "Email", "Company", "Company Number", "Phone", "Is Admin", "Is Active", "Require Password Change", "Total Searches", "Monthly Searches", "Monthly Limit", "License Tier", "Created At", "Updated At"])
    for user in users:
        tier_key = user.get("license_tier") or user_store.DEFAULT_LICENSE_TIER
        try:
            normalized_tier = user_store.normalize_license_tier(tier_key)
        except ValueError:
            normalized_tier = user_store.DEFAULT_LICENSE_TIER
        tier_meta = user_store.LICENSE_TIERS[normalized_tier]
        monthly_limit = tier_meta.get("monthly_limit")
        writer.writerow([
            user.get("username"),
            user.get("name"),
            user.get("email"),
            user.get("company"),
            user.get("company_number"),
            user.get("phone"),
            int(bool(user.get("is_admin"))),
            int(bool(user.get("is_active"))),
            int(bool(user.get("require_password_change"))),
            int(counts.get(user.get("username"), 0)),
            int(monthly_counts.get(user.get("username"), 0)),
            "unlimited" if monthly_limit is None else monthly_limit,
            tier_meta.get("label", normalized_tier.title()),
            user.get("created_at"),
            user.get("updated_at"),
        ])
    csv_content = buffer.getvalue()
    buffer.close()
    filename = f"geoprox-users-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return Response(csv_content, media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})


@app.post("/admin/users/create")
async def admin_create_user(request: Request):
    _require_admin(request)
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = (form.get("password") or "").strip()
    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip()
    company = (form.get("company") or "").strip()
    company_id = _parse_optional_int(form.get("company_id"))
    company_number = (form.get("company_number") or "").strip()
    phone = (form.get("phone") or "").strip()
    license_tier_raw = (form.get("license_tier") or user_store.DEFAULT_LICENSE_TIER).strip()
    is_admin = form.get("is_admin") == "on"
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    if not username or not password or not name:
        _add_flash(request, "Username, name, and password are required.", "error")
    else:
        try:
            license_tier = user_store.normalize_license_tier(license_tier_raw)
        except ValueError:
            _add_flash(request, "Select a valid license tier.", "error")
        else:
            try:
                log.info("admin_create_user debug: USE_POSTGRES=%s DB_HOST=%s", user_store.USE_POSTGRES, os.environ.get("DB_HOST"))
                created = user_store.create_user(
                    username=username,
                    password=password,
                    name=name,
                    email=email,
                    company=company,
                    company_number=company_number,
                    phone=phone,
                    company_id=company_id,
                    is_admin=is_admin,
                    license_tier=license_tier,
                )
                log.info("admin_create_user result truthy=%s data=%s", bool(created), created)
                if created:
                    log.info("Admin created user %s (id=%s, company_id=%s, is_admin=%s, is_active=%s)",
                             username,
                             created.get("id"),
                             created.get("company_id"),
                             created.get("is_admin"),
                             created.get("is_active"))
                    log.info("admin_check persisted: %s", user_store.get_user_by_username(username))
                else:
                    log.warning("Admin create user returned no record for %s", username)
                _add_flash(request, f"User '{username}' created.", "success")
            except sqlite3.IntegrityError:
                _add_flash(request, "Username or email already exists.", "error")
            except ValueError as exc:
                _add_flash(request, str(exc) or "Invalid company selection.", "error")
    return _redirect_admin_users(redirect_company_id)


@app.post("/admin/users/{user_id}/update")
async def admin_update_user(request: Request, user_id: int):
    _require_admin(request)
    form = await request.form()
    user = user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    updates: Dict[str, Any] = {}
    for field in ("name", "email", "company_number", "phone"):
        value = form.get(field)
        if value is not None:
            updates[field] = value.strip()
    company_name = (form.get("company") or "").strip()
    company_id_value = _parse_optional_int(form.get("company_id"))
    if company_name:
        updates["company"] = company_name
        updates["company_id"] = company_id_value
    elif form.get("company_id") is not None:
        updates["company_id"] = company_id_value
        if company_id_value is None:
            updates["company"] = ""
    license_choice = (form.get("license_tier") or "").strip()
    if license_choice:
        try:
            updates["license_tier"] = user_store.normalize_license_tier(license_choice)
        except ValueError:
            _add_flash(request, "Select a valid license tier.", "error")
            return _redirect_admin_users(redirect_company_id)
    is_admin_flag = form.get("is_admin") == "on"
    updates["is_admin"] = is_admin_flag
    require_values = form.getlist("require_password_change")
    if require_values:
        updates["require_password_change"] = require_values[-1] == "on"
    try:
        _ensure_can_change_admin_flag(request, user, is_admin_flag)
    except HTTPException as exc:
        _add_flash(request, exc.detail, "error")
        return _redirect_admin_users(redirect_company_id)
    try:
        user_store.update_user(user["id"], **updates)
    except ValueError as exc:
        _add_flash(request, str(exc) or "Invalid company selection.", "error")
        return _redirect_admin_users(redirect_company_id)
    _add_flash(request, f"Updated profile for '{user['username']}'.", "success")
    return _redirect_admin_users(redirect_company_id)


@app.post("/admin/users/{user_id}/toggle")
async def admin_toggle_user(request: Request, user_id: int):
    _require_admin(request)
    form = await request.form()
    action = form.get("action", "disable")
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    user = user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    enable = action != "disable"
    try:
        _ensure_can_change_active_status(request, user, enable=enable)
    except HTTPException as exc:
        _add_flash(request, exc.detail, "error")
        return _redirect_admin_users(redirect_company_id)
    if enable:
        user_store.enable_user(user["id"])
        _add_flash(request, f"Enabled '{user['username']}'.", "success")
    else:
        user_store.disable_user(user["id"])
        _add_flash(request, f"Disabled '{user['username']}'.", "success")
    return _redirect_admin_users(redirect_company_id)


@app.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(request: Request, user_id: int):
    _require_admin(request)
    form = await request.form()
    new_password = (form.get("new_password") or "").strip()
    user = user_store.get_user_by_id(user_id)
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not new_password:
        _add_flash(request, "Password cannot be empty.", "error")
    else:
        user_store.set_password(user["id"], new_password, require_change=True)
        _add_flash(request, f"Password updated for '{user['username']}'.", "success")
    return _redirect_admin_users(redirect_company_id)


@app.post("/admin/users/{user_id}/delete")
async def admin_delete_user(request: Request, user_id: int):
    _require_admin(request)
    form = await request.form()
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    user = user_store.get_user_by_id(user_id)
    if not user:
        _add_flash(request, "User not found.", "error")
        return _redirect_admin_users(redirect_company_id)
    current_username = (request.session.get("user") or "").lower()
    if user["username"].lower() == current_username:
        _add_flash(request, "You cannot delete your own account.", "error")
        return _redirect_admin_users(redirect_company_id)
    if user["is_admin"]:
        remaining_admins = [u for u in user_store.list_users(include_disabled=True) if u["is_admin"] and u["id"] != user["id"]]
        if not remaining_admins:
            _add_flash(request, "At least one administrator must remain.", "error")
            return _redirect_admin_users(redirect_company_id)
    history_store.delete_history(user["username"])
    user_store.delete_user(user["id"])
    _add_flash(request, f"Deleted '{user['username']}'.", "success")
    return _redirect_admin_users(redirect_company_id)

@app.post("/admin/companies/create")
async def admin_create_company_form(request: Request):
    _require_admin(request)
    form = await request.form()
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    name = (form.get("name") or "").strip()
    company_number = (form.get("company_number") or "").strip()
    phone = (form.get("phone") or "").strip()
    email = (form.get("email") or "").strip()
    notes = (form.get("notes") or "").strip()
    if not name:
        _add_flash(request, "Company name is required.", "error")
    else:
        try:
            user_store.create_company(
                name=name,
                company_number=company_number,
                phone=phone,
                email=email,
                notes=notes,
            )
            _add_flash(request, f"Company '{name}' created.", "success")
        except sqlite3.IntegrityError:
            _add_flash(request, "Company name already exists.", "error")
    return _redirect_admin_users(redirect_company_id)


@app.post("/admin/companies/{company_id}/update")
async def admin_update_company_form(request: Request, company_id: int):
    _require_admin(request)
    form = await request.form()
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    company = user_store.get_company_by_id(company_id)
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    action = (form.get("action") or "update").lower()
    if action == "activate":
        user_store.update_company(company_id, is_active=True)
        _add_flash(request, f"Company '{company['name']}' activated.", "success")
        return _redirect_admin_users(redirect_company_id)
    if action == "deactivate":
        user_store.update_company(company_id, is_active=False)
        _add_flash(request, f"Company '{company['name']}' deactivated.", "success")
        return _redirect_admin_users(redirect_company_id)
    updates = {}
    for field in ("name", "company_number", "phone", "email", "notes"):
        value = form.get(field)
        if value is not None:
            updates[field] = value.strip()
    if updates:
        user_store.update_company(company_id, **updates)
        _add_flash(request, "Company details updated.", "success")
    else:
        _add_flash(request, "Nothing to update.", "info")
    return _redirect_admin_users(redirect_company_id)


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------


@app.get("/api/admin/users", response_model=List[AdminUserOut])
async def api_admin_list_users(
    request: Request,
    company_id: Optional[int] = None,
    include_disabled: bool = True,
) -> List[AdminUserOut]:
    _require_admin(request)
    records = user_store.list_users(include_disabled=include_disabled, company_id=company_id)
    counts = history_store.get_user_search_counts()
    monthly_counts = history_store.get_user_monthly_search_counts()
    return [_user_to_out(record, counts, monthly_counts) for record in records]


@app.get("/api/admin/users/{user_id}", response_model=AdminUserOut)
async def api_admin_get_user(request: Request, user_id: int) -> AdminUserOut:
    _require_admin(request)
    record = user_store.get_user_by_id(user_id)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    counts = history_store.get_user_search_counts()
    monthly_counts = {record['username']: history_store.get_monthly_search_count(record['username'])}
    return _user_to_out(record, counts, monthly_counts)


@app.post("/api/admin/users", response_model=AdminUserOut, status_code=201)
async def api_admin_create_user(request: Request, payload: AdminUserCreate) -> AdminUserOut:
    _require_admin(request)
    username = payload.username.strip()
    name = payload.name.strip()
    if not username or not name:
        raise HTTPException(status_code=400, detail="Username and name are required.")
    try:
        record = user_store.create_user(
            username=username,
            password=payload.password,
            name=name,
            email=(payload.email or "").strip(),
            company=(payload.company or "").strip(),
            company_number=(payload.company_number or "").strip(),
            phone=(payload.phone or "").strip(),
            company_id=payload.company_id,
            is_admin=payload.is_admin,
            is_active=payload.is_active,
            require_password_change=payload.require_password_change,
            license_tier=payload.license_tier,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Username already exists.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid company selection.")
    counts = history_store.get_user_search_counts()
    monthly_counts = {record['username']: history_store.get_monthly_search_count(record['username'])}
    return _user_to_out(record, counts, monthly_counts)


@app.patch("/api/admin/users/{user_id}", response_model=AdminUserOut)
async def api_admin_update_user(request: Request, user_id: int, payload: AdminUserUpdate) -> AdminUserOut:
    _require_admin(request)
    record = user_store.get_user_by_id(user_id)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    data = payload.model_dump(exclude_unset=True)
    updates: Dict[str, Any] = {}
    for field in ("name", "email", "company_number", "phone"):
        if field in data and data[field] is not None:
            updates[field] = data[field].strip()
    if "company" in data:
        updates["company"] = (data["company"] or "").strip()
    if "company_id" in data:
        updates["company_id"] = data["company_id"]
        if data["company_id"] is None and "company" not in updates:
            updates["company"] = ""
    if "is_admin" in data:
        _ensure_can_change_admin_flag(request, record, data["is_admin"])
        updates["is_admin"] = data["is_admin"]
    if "require_password_change" in data:
        updates["require_password_change"] = data["require_password_change"]
    if "license_tier" in data:
        updates["license_tier"] = data["license_tier"]
    target_is_admin = updates.get("is_admin", record["is_admin"])
    if "is_active" in data:
        _ensure_can_change_active_status(
            request,
            record,
            enable=data["is_active"],
            target_is_admin=target_is_admin,
        )
        updates["is_active"] = data["is_active"]
    if not updates:
        counts = history_store.get_user_search_counts()
        monthly_counts = {record['username']: history_store.get_monthly_search_count(record['username'])}
        return _user_to_out(record, counts, monthly_counts)
    try:
        user_store.update_user(record["id"], **updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid company selection.")
    updated = user_store.get_user_by_id(record["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    counts = history_store.get_user_search_counts()
    monthly_counts = {updated['username']: history_store.get_monthly_search_count(updated['username'])}
    return _user_to_out(updated, counts, monthly_counts)


@app.post("/api/admin/users/{user_id}/reset-password", response_model=AdminActionResult)
async def api_admin_reset_password(request: Request, user_id: int, payload: AdminPasswordReset) -> AdminActionResult:
    _require_admin(request)
    new_password = payload.new_password.strip()
    if not new_password:
        raise HTTPException(status_code=400, detail="Password cannot be empty.")
    user = user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_store.set_password(user_id, new_password, require_change=True)
    return AdminActionResult(status="ok", message=f"Password updated for '{user['username']}'.")



@app.get("/api/admin/companies", response_model=List[AdminCompanyOut])
async def api_admin_list_companies(request: Request, include_inactive: bool = True) -> List[AdminCompanyOut]:
    _require_admin(request)
    records = user_store.list_companies(include_inactive=include_inactive)
    return [_company_to_out(record) for record in records]


@app.get("/api/admin/companies/{company_id}", response_model=AdminCompanyOut)
async def api_admin_get_company(request: Request, company_id: int) -> AdminCompanyOut:
    _require_admin(request)
    record = user_store.get_company_by_id(company_id)
    if not record:
        raise HTTPException(status_code=404, detail="Company not found")
    return _company_to_out(record)


@app.post("/api/admin/companies", response_model=AdminCompanyOut, status_code=201)
async def api_admin_create_company(request: Request, payload: AdminCompanyCreate) -> AdminCompanyOut:
    _require_admin(request)
    try:
        record = user_store.create_company(
            name=payload.name,
            company_number=(payload.company_number or "").strip(),
            phone=(payload.phone or "").strip(),
            email=(payload.email or "").strip(),
            notes=(payload.notes or "").strip(),
            is_active=payload.is_active,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Company name already exists.")
    return _company_to_out(record)


@app.patch("/api/admin/companies/{company_id}", response_model=AdminCompanyOut)
async def api_admin_update_company(request: Request, company_id: int, payload: AdminCompanyUpdate) -> AdminCompanyOut:
    _require_admin(request)
    record = user_store.get_company_by_id(company_id)
    if not record:
        raise HTTPException(status_code=404, detail="Company not found")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return _company_to_out(record)
    user_store.update_company(company_id, **data)
    updated = user_store.get_company_by_id(company_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Company not found")
    return _company_to_out(updated)



@app.post("/api/permits", response_model=PermitRecordResp)
def api_save_permit_record(request: Request, payload: PermitSaveReq):
    username = _require_user(request)
    permit_ref = (payload.permit_ref or "").strip()
    if not permit_ref:
        raise HTTPException(status_code=400, detail="Permit reference is required.")
    record = permit_store.save_permit(
        username=username,
        permit_ref=permit_ref,
        search_result=payload.result or {},
    )
    if not record:
        raise HTTPException(status_code=500, detail="Unable to save permit record.")
    return _permit_to_response(record)


@app.get("/api/permits/{permit_ref}", response_model=PermitRecordResp)
def api_get_permit_record(request: Request, permit_ref: str):
    username = _require_user(request)
    ref = (permit_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="Permit reference is required.")
    record = permit_store.get_permit(username, ref)
    if not record:
        raise HTTPException(status_code=404, detail="Permit record not found.")
    return _permit_to_response(record)


@app.post("/api/permits/{permit_ref}/site-assessment", response_model=PermitRecordResp)
def api_update_site_assessment(request: Request, permit_ref: str, payload: PermitSiteUpdateReq):
    username = _require_user(request)
    ref = (permit_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="Permit reference is required.")
    status = (payload.status or "").strip() or "Completed"
    outcome = (payload.outcome or "").strip() or None
    notes = (payload.notes or "").strip() or None
    payload_data = payload.payload if isinstance(payload.payload, dict) else None
    record = permit_store.update_site_assessment(
        username=username,
        permit_ref=ref,
        status=status,
        outcome=outcome,
        notes=notes,
        payload=payload_data,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Permit record not found.")
    return _permit_to_response(record)

@app.post("/api/search", response_model=SearchResp)
def api_search(request: Request, req: SearchReq):
    username = _require_user(request)
    user_record = user_store.get_user_by_username(username)
    if not user_record:
        raise HTTPException(status_code=401, detail="User account not found")
    try:
        license_tier = user_store.normalize_license_tier(user_record.get("license_tier"))
    except ValueError:
        license_tier = user_store.DEFAULT_LICENSE_TIER
    monthly_limit = user_store.get_license_monthly_limit(license_tier)
    if monthly_limit is not None:
        used_this_month = history_store.get_monthly_search_count(username)
        if used_this_month >= monthly_limit:
            tier_label = user_store.LICENSE_TIERS[license_tier]["label"]
            message = (
                f"You have used all {monthly_limit} searches included in your {tier_label} license this month. "
                "Please upgrade to continue searching."
            )
            log.info(
                "Monthly search limit reached for %s (tier=%s, used=%s, limit=%s)",
                username,
                license_tier,
                used_this_month,
                monthly_limit,
            )
            return SearchResp(status="error", error=message)
    try:
        w3w_key = _load_w3w_key()
        log.info(f"Incoming request: {req.dict()}")

        selection_mode = (req.selection_mode or "point").lower()
        if selection_mode not in {"point", "polygon"}:
            raise HTTPException(status_code=400, detail="Invalid selection mode.")

        polygon_vertices: Optional[List[Tuple[float, float]]] = None
        if selection_mode == "polygon":
            polygon_vertices, centroid = _validate_polygon_coords(req.polygon or [])
            location_value = f"{centroid[0]},{centroid[1]}"
        else:
            location_value = req.location

        safe_location = _normalise_location(location_value)

        result = run_geoprox_search(
            location=safe_location,
            radius_m=req.radius_m,
            categories=req.categories,
            permit=req.permit or "",
            out_dir=ARTIFACTS_DIR,
            w3w_key=w3w_key,
            max_results=req.max_results,
            user_name=username,
            selection_mode=selection_mode,
            polygon=polygon_vertices,
        )

        log.info(f"Search result: {result}")

        if not result:
            raise RuntimeError("run_geoprox_search returned None")

        arts = result.get("artifacts", {}) or {}
        if arts.get("pdf_path") and not arts.get("pdf_url"):
            arts["pdf_url"] = f"/artifacts/{Path(arts['pdf_path']).name}"
        if arts.get("map_html_url") and not arts.get("map_url"):
            arts["map_url"] = arts["map_html_url"]
        if arts.get("map_html_url") and not arts.get("map_embed_url"):
            arts["map_embed_url"] = arts["map_html_url"]
        if arts.get("map_html_path") and not arts.get("map_url"):
            arts["map_url"] = f"/artifacts/{Path(arts['map_html_path']).name}"
        if arts.get("map_image_path") and not arts.get("map_image_url"):
            arts["map_image_url"] = f"/artifacts/{Path(arts['map_image_path']).name}"

        result["artifacts"] = arts

        selection_info = result.get("selection") or {}
        if "mode" not in selection_info:
            selection_info["mode"] = selection_mode
        if polygon_vertices and not selection_info.get("polygon"):
            selection_info["polygon"] = [[float(lat), float(lon)] for lat, lon in polygon_vertices]
        result["selection"] = selection_info

        timestamp = datetime.utcnow().isoformat() + "Z"
        outcome = result.get("summary", {}).get("outcome")
        pdf_name = Path(arts["pdf_path"]).name if arts.get("pdf_path") else None
        map_name = Path(arts["map_html_path"]).name if arts.get("map_html_path") else None

        history_store.record_search(
            username=username,
            timestamp=timestamp,
            location=safe_location,
            radius_m=req.radius_m,
            outcome=outcome,
            permit=req.permit,
            pdf_path=pdf_name,
            map_path=map_name,
            result=result,
        )

        entry = {"timestamp": timestamp,
                 "location": safe_location,
                 "radius_m": req.radius_m,
                 "outcome": outcome,
                 "permit": req.permit,
                 "mode": selection_info.get("mode", selection_mode)}
        history = request.session.get("history") or []
        history.append(entry)
        request.session["history"] = history[-20:]

        return SearchResp(status="done", result=result)

    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=6)
        log.error(f"GeoProx error: {e}\n{tb}")
        return SearchResp(status="error", error=str(e), debug={"trace": tb})







