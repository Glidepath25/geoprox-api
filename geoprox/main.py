# geoprox/main.py
from __future__ import annotations

import os
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field

from geoprox import history_store, user_store
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
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not full.exists():
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
    history_rows = history_store.get_history(user["username"], limit=20)
    session_history = []
    for row in reversed(history_rows):
        session_history.append({
            "timestamp": row["timestamp"],
            "location": row["location"],
            "radius_m": int(row.get("radius_m", 0)),
            "outcome": row.get("outcome"),
            "permit": row.get("permit"),
            "mode": "point",
        })
    request.session["history"] = session_history


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


def _user_to_out(user: Dict[str, Any]) -> AdminUserOut:
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



# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if request.session.get("user"):
        return RedirectResponse(url="/app", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "username": ""})


@app.post("/login", response_class=HTMLResponse)
async def login_action(request: Request, username: str = Form(...), password: str = Form(...)) -> HTMLResponse:
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
        return RedirectResponse(url="/app", status_code=303)
    else:
        error = "Invalid username or password."
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error, "username": username},
        status_code=401,
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
    return RedirectResponse(url="/app", status_code=303)


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request) -> HTMLResponse:
    if request.session.get("user"):
        return RedirectResponse(url="/app", status_code=303)
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
                    return RedirectResponse(url="/app", status_code=303)
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
        },
    )


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
    is_admin = form.get("is_admin") == "on"
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    if not username or not password or not name:
        _add_flash(request, "Username, name, and password are required.", "error")
    else:
        try:
            user_store.create_user(
                username=username,
                password=password,
                name=name,
                email=email,
                company=company,
                company_number=company_number,
                phone=phone,
                company_id=company_id,
                is_admin=is_admin,
            )
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
    is_admin_flag = form.get("is_admin") == "on"
    updates["is_admin"] = is_admin_flag
    if form.get("require_password_change_present") is not None:
        updates["require_password_change"] = form.get("require_password_change") == "on"
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
    return [_user_to_out(record) for record in records]


@app.get("/api/admin/users/{user_id}", response_model=AdminUserOut)
async def api_admin_get_user(request: Request, user_id: int) -> AdminUserOut:
    _require_admin(request)
    record = user_store.get_user_by_id(user_id)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_to_out(record)


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
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Username already exists.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid company selection.")
    return _user_to_out(record)


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
        return _user_to_out(record)
    try:
        user_store.update_user(record["id"], **updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid company selection.")
    updated = user_store.get_user_by_id(record["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_to_out(updated)


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


@app.post("/api/search", response_model=SearchResp)
def api_search(request: Request, req: SearchReq):
    username = _require_user(request)
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





