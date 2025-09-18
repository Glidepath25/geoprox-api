# geoprox/main.py
from __future__ import annotations

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field

from geoprox.core import run_geoprox_search
from geoprox.auth import load_users, verify_user

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
    users = load_users()
    if verify_user(users, username, password):
        request.session["user"] = username
        if request.session.get("history") is None:
            request.session["history"] = []
        log.info("User %s logged in", username)
        return RedirectResponse(url="/app", status_code=303)
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


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class SearchReq(BaseModel):
    location: str = Field(..., description="lat,lon or ///what.three.words")
    radius_m: int = Field(..., ge=10, le=20000, examples=[2000])
    categories: List[str] = Field(default_factory=list)
    permit: Optional[str] = None
    max_results: Optional[int] = Field(default=None, ge=1, le=10000)


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
    _require_user(request)
    return {"history": request.session.get("history") or []}


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


@app.post("/api/search", response_model=SearchResp)
def api_search(request: Request, req: SearchReq):
    _require_user(request)
    try:
        w3w_key = _load_w3w_key()
        log.info(f"Incoming request: {req.dict()}")

        safe_location = _normalise_location(req.location)

        result = run_geoprox_search(
            location=safe_location,
            radius_m=req.radius_m,
            categories=req.categories,
            permit=req.permit or "",
            out_dir=ARTIFACTS_DIR,
            w3w_key=w3w_key,
            max_results=req.max_results,
        )

        log.info(f"Search result: {result}")

        if not result:
            raise RuntimeError("run_geoprox_search returned None")

        arts = result.get("artifacts", {}) or {}
        if arts.get("pdf_path") and not arts.get("pdf_url"):
            arts["pdf_url"] = f"/artifacts/{Path(arts['pdf_path']).name}"
        if arts.get("map_html_path") and not arts.get("map_url"):
            arts["map_url"] = f"/artifacts/{Path(arts['map_html_path']).name}"

        result["artifacts"] = arts

        entry = {"timestamp": datetime.utcnow().isoformat() + "Z",
                 "location": safe_location,
                 "radius_m": req.radius_m,
                 "outcome": result.get("summary", {}).get("outcome")}
        history = request.session.get("history") or []
        history.append(entry)
        request.session["history"] = history[-20:]

        return SearchResp(status="done", result=result)

    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=6)
        log.error(f"GeoProx error: {e}\n{tb}")
        return SearchResp(status="error", error=str(e), debug={"trace": tb})
