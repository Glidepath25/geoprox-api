# geoprox/main.py
from __future__ import annotations

import os
import logging
import sqlite3
import csv
import smtplib
import ssl
import mimetypes
import re
import secrets
import time
import requests
from email.message import EmailMessage
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
try:
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except Exception:  # pragma: no cover - boto3 optional
    boto3 = None
    BotoCoreError = ClientError = Exception
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.datastructures import UploadFile
from pydantic import BaseModel, Field
import pandas as pd

from geoprox import history_store, permit_store, report_store, user_store
from geoprox.auth_tokens import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from geoprox.core import SEARCH_CATEGORY_LABELS, SEARCH_CATEGORY_OPTIONS, run_geoprox_search
from geoprox.mobile_auth_models import (
    MobileAuthRequest,
    MobileAuthResponse,
    MobileRefreshRequest,
)
from geoprox.sample_testing_pdf import generate_sample_testing_pdf
from geoprox.site_assessment_pdf import generate_site_assessment_pdf

SITE_ASSESSMENT_DETAIL_FIELDS = [
    ('utility_type', 'Utility Type'),
    ('assessment_date', 'Date of Assessment'),
    ('permit_number', 'Permit Number'),
    ('excavation_site_number', 'Excavation Site Number'),
    ('site_address', 'Address'),
    ('highway_authority', 'Highway Authority'),
    ('works_type', 'Works Type'),
    ('surface_location', 'Surface Locations'),
    ('what_three_words', 'What Three Words'),
]
SITE_ASSESSMENT_QUESTION_SECTIONS = [
    (
        'General',
        [
            (
                'q1_asbestos',
                'Are there any signs of asbestos fibres or asbestos containing materials in the excavation?',
                'If asbestos or signs of asbestos are identified the excavation does not qualify for a risk assessment.'
            ),
        ],
    ),
    (
        'Asphalt / Bitumen Road Surfaces',
        [
            (
                'q2_binder_shiny',
                'Is the binder shiny, sticky to touch and is there an organic odour?',
                'All three (shiny, sticky and creosote odour) required for a "yes".'
            ),
            (
                'q3_spray_pak',
                'Spray PAK across the profile of asphalt / bitumen. Does the paint change colour to Band 1 or 2?',
                'Ensure to spray a line across the full depth of the bituminous layer. Refer to PAK colour chart.'
            ),
        ],
    ),
    (
        'All Mobilised Wastes / Materials',
        [
            (
                'q4_soil_colour',
                'Is the soil stained an unusual colour (such as orange, black, blue or green)?',
                'Compare the discolouration of soil to other parts of the excavation.'
            ),
            (
                'q5_water_sheen',
                'If there is water or moisture in the excavation, is there a rainbow sheen or colouration to the water?',
                'Looking for signs of oil in the excavation.'
            ),
            (
                'q6_pungent_odour',
                'Are there any pungent odours to the material?',
                'Think bleach, garlic, egg, tar, gas or other strong smells.'
            ),
            (
                'q7_litmus_change',
                'Use litmus paper on wet soil, does it change colour to high or low pH?',
                'Refer to the pH colour chart.'
            ),
        ],
    ),
]
SITE_ASSESSMENT_QUESTIONS = [
    (key, question, note)
    for _, rows in SITE_ASSESSMENT_QUESTION_SECTIONS
    for key, question, note in rows
]
SITE_ASSESSMENT_RESULT_FIELDS = [
    ('result_bituminous', 'Bituminous'),
    ('result_sub_base', 'Sub-base'),
]
SITE_ASSESSMENT_FIELD_LABELS = (
    SITE_ASSESSMENT_DETAIL_FIELDS
    + [(key, question) for key, question, _ in SITE_ASSESSMENT_QUESTIONS]
    + [(key, f"Assessment Result ({label})") for key, label in SITE_ASSESSMENT_RESULT_FIELDS]
    + [
        ('assessor_name', 'Assessor Name'),
        ('site_notes', 'Site Notes'),
    ]
)
SITE_ASSESSMENT_LOCATION_OPTIONS = ['Public', 'Private']
SITE_ASSESSMENT_WORKS_TYPE_OPTIONS = ['Immediate', 'Minor', 'Standard', 'Major (TM Only)']
SITE_ASSESSMENT_SURFACE_OPTIONS = ['Carriageway', 'Footway / Footpath', 'Verge', 'Other']
SITE_ASSESSMENT_STATUS_OPTIONS = [
    ('Not started', 'Not started'),
    ('In progress', 'In progress'),
    ('Completed', 'Completed'),
]
SITE_ASSESSMENT_RESULT_CHOICES = ['Green', 'Red', 'N/A']
SITE_ASSESSMENT_YES_NO_CHOICES = ['Yes', 'No']
SITE_ASSESSMENT_YES_NO_NA_CHOICES = ['Yes', 'No', 'N/A']
SITE_ASSESSMENT_YES_NO_NA_KEYS = {'q3_spray_pak', 'q7_litmus_change'}
SITE_ASSESSMENT_ATTACHMENT_CATEGORIES = [
    ('pak', 'PAK spray result'),
    ('litmus', 'Litmus paper result'),
    ('general', 'General'),
]
SITE_ASSESSMENT_ATTACHMENT_LABELS = {key: label for key, label in SITE_ASSESSMENT_ATTACHMENT_CATEGORIES}
SITE_ASSESSMENT_ALLOWED_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'}
SITE_ASSESSMENT_ALLOWED_IMAGE_MIME_MAP = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/heic': '.heic',
    'image/heif': '.heif',
}

SAMPLE_TESTING_STATUS_OPTIONS = [
    ('Not required', 'Not required'),
    ('Pending sample', 'Pending sample'),
    ('Pending result', 'Pending result'),
    ('Complete', 'Complete'),
]
SAMPLE_TESTING_STATUS_DEFAULT = 'Not required'
SAMPLE_TESTING_STATUS_LABELS = {value: label for value, label in SAMPLE_TESTING_STATUS_OPTIONS}
SAMPLE_TESTING_MATERIAL_OPTIONS = ['Bituminous', 'Sub-base']
SAMPLE_TESTING_LAB_RESULT_OPTIONS = ['Green', 'Red']
SAMPLE_TESTING_ENTRY_KEYS = [
    ('sample_1', 'Sample 1'),
    ('sample_2', 'Sample 2'),
]
SAMPLE_TESTING_DETERMINANTS = [
    ('coal_tar', 'Coal Tar (determined by BaP)'),
    ('tph', 'Total Petroleum Hydrocarbons (C6-C40)'),
    ('heavy_metal', 'Heavy Metal'),
    ('asbestos', 'Asbestos'),
    ('other', 'Other'),
]
SAMPLE_TESTING_ATTACHMENT_CATEGORIES = [
    ('field_photo', 'Field photo'),
    ('lab_report', 'Lab result'),
    ('general', 'General attachment'),
]
SAMPLE_TESTING_ATTACHMENT_LABELS = {key: label for key, label in SAMPLE_TESTING_ATTACHMENT_CATEGORIES}
UNIDENTIFIED_REPORT_CATEGORY_OPTIONS = [
    ("industrial", "Industrial site"),
    ("gas_holder", "Gas holder"),
    ("mining", "Mining or quarry site"),
    ("petrol_station", "Petrol station"),
    ("other", "Other"),
]
UNIDENTIFIED_REPORT_CATEGORY_LABELS = {key: label for key, label in UNIDENTIFIED_REPORT_CATEGORY_OPTIONS}

SEARCH_CATEGORY_KEYS = {key for key, _ in SEARCH_CATEGORY_OPTIONS}
UNIDENTIFIED_TO_SEARCH_CATEGORY = {
    "industrial": "manufacturing",
    "gas_holder": "gas_holding",
    "mining": "mines",
    "petrol_station": "petrol_stations",
}
_SEARCH_CATEGORY_FALLBACK = "waste_disposal"


def _default_search_category_for_report(category: Optional[str]) -> str:
    key = str(category or "").strip().lower()
    suggested = UNIDENTIFIED_TO_SEARCH_CATEGORY.get(key, _SEARCH_CATEGORY_FALLBACK)
    if suggested not in SEARCH_CATEGORY_KEYS:
        return next(iter(SEARCH_CATEGORY_KEYS)) if SEARCH_CATEGORY_KEYS else _SEARCH_CATEGORY_FALLBACK
    return suggested

SAMPLE_TESTING_FIELD_LABELS = [
    ('sampling_date', 'Sampling date'),
    ('sampled_by_name', 'Sampled by'),
    ('results_recorded_by', 'Results recorded by'),
]
MAX_SITE_ATTACHMENT_SIZE = 5 * 1024 * 1024



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

S3_BUCKET = os.environ.get("GEOPROX_BUCKET", "").strip()
S3_ARTIFACT_PREFIX = os.environ.get("GEOPROX_ARTIFACT_PREFIX", "").strip()
_S3_CLIENT = None

SUPPORT_EMAIL = os.environ.get("GEOPROX_SUPPORT_EMAIL", "useradmin@geoprox.co.uk")
SIGNUP_NOTIFY_EMAIL = os.environ.get("SIGNUP_NOTIFY_EMAIL", SUPPORT_EMAIL)
GRAPH_TENANT_ID = os.environ.get("GRAPH_TENANT_ID")
GRAPH_CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID")
GRAPH_CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET")
GRAPH_SENDER_UPN = os.environ.get("GRAPH_SENDER_UPN")

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
    value = s.strip()
    if not value:
        raise HTTPException(status_code=400, detail="Location is required.")
    if value.startswith("///"):
        return value

    decimal_pair = _try_parse_decimal_location(value)
    if decimal_pair:
        lat, lon = decimal_pair
        return f"{lat},{lon}"

    tokens = _split_location_tokens(value)
    if tokens and len(tokens) == 2:
        try:
            lat = _parse_dms_coordinate(tokens[0], is_lat=True)
            lon = _parse_dms_coordinate(tokens[1], is_lat=False)
            return f"{lat},{lon}"
        except ValueError:
            pass

    raise HTTPException(
        status_code=400,
        detail=(
            "Invalid location. Use decimal lat/lon (e.g. 54.35,-6.65), "
            "DMS (e.g. 54?53'13\"N, 002?55'40\"W), "
            'or a "///what.three.words" address.'
        ),
    )


_DMS_CARDINALS = {"N", "S", "E", "W"}


def _try_parse_decimal_location(value: str) -> Optional[Tuple[float, float]]:
    cleaned = re.sub(r"\s+", "", value)
    parts = cleaned.split(",")
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _normalise_dms_symbols(value: str) -> str:
    replacements = {
        "\u00BA": "\u00B0",
        "\u02DA": "\u00B0",
        "\u2019": "'",
        "\u2032": "'",
        "\u201D": '"',
        "\u201C": '"',
        "\u2033": '"',
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    return value


def _split_location_tokens(value: str) -> Optional[List[str]]:
    normalised = _normalise_dms_symbols(value)
    comma_parts = [part.strip() for part in re.split(r"\s*,\s*", normalised) if part.strip()]
    if len(comma_parts) == 2:
        return comma_parts

    tokens: List[str] = []
    buffer: List[str] = []
    for ch in normalised:
        buffer.append(ch)
        if ch.upper() in _DMS_CARDINALS:
            token = "".join(buffer).strip()
            if token:
                tokens.append(token)
            buffer = []
            if len(tokens) == 2:
                break
    if len(tokens) == 2:
        remainder = "".join(buffer).strip()
        if remainder:
            tokens[-1] = f"{tokens[-1]} {remainder}".strip()
        return tokens
    return None


def _parse_dms_coordinate(token: str, is_lat: bool) -> float:
    cleaned = _normalise_dms_symbols((token or "")).strip()
    if not cleaned:
        raise ValueError("Empty coordinate")

    upper = cleaned.upper()
    sign = 1
    if upper.startswith("-"):
        sign = -1
        upper = upper[1:].strip()
    elif upper.startswith("+"):
        upper = upper[1:].strip()

    direction: Optional[str] = None
    if upper and upper[-1] in _DMS_CARDINALS:
        direction = upper[-1]
        upper = upper[:-1].strip()

    numeric = upper
    numeric = numeric.replace("\u00B0", " ")
    numeric = numeric.replace("'", " ")
    numeric = numeric.replace('"', " ")
    numeric = re.sub(r"[\u2019\u2032]", " ", numeric)
    numeric = re.sub(r"[\u201C\u201D\u2033]", " ", numeric)
    numeric = re.sub(r"\s+", " ", numeric).strip()
    if not numeric:
        raise ValueError("Missing numeric component")

    parts = numeric.split(" ")
    if len(parts) > 3:
        raise ValueError("Too many coordinate components")

    try:
        deg = float(parts[0])
        minutes = float(parts[1]) if len(parts) >= 2 else 0.0
        seconds = float(parts[2]) if len(parts) >= 3 else 0.0
    except ValueError as exc:
        raise ValueError("Invalid DMS component") from exc

    if minutes >= 60 or seconds >= 60:
        raise ValueError("Minutes/seconds out of range")

    value = abs(deg) + minutes / 60.0 + seconds / 3600.0

    if direction:
        if direction in {"S", "W"}:
            value = -value
    elif sign < 0 or deg < 0:
        value = -value

    limit = 90.0 if is_lat else 180.0
    if not (-limit <= value <= limit):
        raise ValueError("Coordinate out of range")

    return value




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
        client = _get_s3_client_cached()
        if client:
            try:
                relative = full.relative_to(ARTIFACTS_DIR).as_posix()
                key = _artifact_s3_key_from_relative(relative)
                if key:
                    full.parent.mkdir(parents=True, exist_ok=True)
                    client.download_file(S3_BUCKET, key, str(full))
            except Exception:
                log.exception("Failed to download artifact from S3 path=%s", path)
        if full.exists():
            return full
        available = []
        try:
            available = sorted(p.name for p in ARTIFACTS_DIR.glob('*'))[:20]
        except Exception:
            available = []
        log.warning("artifact missing path=%s base=%s available=%s", full, ARTIFACTS_DIR, available)
        raise HTTPException(status_code=404, detail="Not Found")
    return full


def _extract_bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization")
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, value = parts[0].strip(), parts[1].strip()
    if scheme.lower() != "bearer":
        return None
    return value or None


def _determine_user_type(raw_value: Optional[str]) -> str:
    try:
        return user_store.normalize_user_type(raw_value)
    except ValueError:
        return user_store.DEFAULT_USER_TYPE


def _cache_user_context(
    request: Request,
    record: Dict[str, Any],
    *,
    session_token: str,
    via_session: bool,
) -> None:
    normalized_type = _determine_user_type(record.get("user_type"))
    is_admin = bool(record.get("is_admin"))
    is_company_admin = bool(record.get("is_company_admin"))
    scope = _build_user_scope(record)

    request.state.current_user = record
    request.state.user_type = normalized_type
    request.state.is_admin = is_admin
    request.state.is_company_admin = is_company_admin
    request.state.session_token = session_token
    request.state.authenticated_via = "session" if via_session else "bearer"
    request.state.scope = scope

    if via_session:
        request.session["user_type"] = normalized_type
        request.session["is_admin"] = is_admin
        request.session["is_company_admin"] = is_company_admin


def _build_user_scope(record: Dict[str, Any]) -> str:
    parts: List[str] = [_determine_user_type(record.get("user_type"))]
    if record.get("is_admin"):
        parts.append("admin")
    elif record.get("is_company_admin"):
        parts.append("company_admin")
    return " ".join(parts)


def _require_user(request: Request) -> str:

    bearer = _extract_bearer_token(request)
    if bearer:
        try:
            payload = decode_access_token(bearer)
        except TokenError as exc:
            raise HTTPException(status_code=401, detail="Invalid authentication token") from exc
        username = payload.get("sub")
        session_token = payload.get("stk")
        if not isinstance(username, str) or not isinstance(session_token, str):
            raise HTTPException(status_code=401, detail="Invalid authentication token")
        record = user_store.get_user_by_username(username)
        if not record or not record.get("is_active"):
            raise HTTPException(status_code=401, detail="Authentication required")
        stored_token = record.get("session_token")
        if not stored_token or stored_token != session_token:
            raise HTTPException(status_code=401, detail="Authentication required")
        _cache_user_context(request, record, session_token=session_token, via_session=False)
        return username

    username = request.session.get("user")

    session_token = request.session.get("session_token")

    current = getattr(request.state, "current_user", None)

    if not username or not session_token:

        request.session.clear()

        raise HTTPException(status_code=401, detail="Authentication required")

    record: Optional[Dict[str, Any]] = None

    if isinstance(current, dict) and current.get("username") == username:

        record = current

    if not record or record.get("session_token") != session_token:

        record = user_store.get_user_by_username(username)

    if not record or not record.get("is_active"):

        request.session.clear()

        raise HTTPException(status_code=401, detail="Authentication required")

    stored_token = record.get("session_token")

    if not stored_token or stored_token != session_token:

        request.session.clear()

        raise HTTPException(status_code=401, detail="Authentication required")

    _cache_user_context(request, record, session_token=session_token, via_session=True)

    return username


def _get_current_user_record(request: Request) -> Dict[str, Any]:
    record = getattr(request.state, "current_user", None)
    if isinstance(record, dict) and record.get("username"):
        return record
    username = request.session.get("user")
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    fresh = user_store.get_user_by_username(username)
    if not fresh or not fresh.get("is_active"):
        request.session.clear()
        raise HTTPException(status_code=401, detail="Authentication required")
    request.state.current_user = fresh
    return fresh

def _require_user_manager(request: Request) -> Tuple[Dict[str, Any], bool]:
    username = _require_user(request)
    record = _get_current_user_record(request)
    is_global_admin = bool(record.get("is_admin"))
    if is_global_admin:
        return record, True
    if bool(record.get("is_company_admin")) and record.get("company_id"):
        return record, False
    raise HTTPException(status_code=403, detail="User management access required")

def _require_user_management_scope(request: Request) -> Tuple[Dict[str, Any], bool, Optional[int]]:
    record, is_global_admin = _require_user_manager(request)
    company_id = record.get("company_id") if not is_global_admin else None
    return record, is_global_admin, company_id


def _ensure_user_in_scope(manager_record: Dict[str, Any], target_user: Dict[str, Any]) -> None:
    if manager_record.get("is_admin"):
        return
    manager_company_id = manager_record.get("company_id")
    if manager_company_id and manager_company_id == target_user.get("company_id"):
        return
    raise HTTPException(status_code=403, detail="You can only manage users in your company.")



def _require_admin(request: Request) -> str:

    user = _require_user(request)

    if not (request.session.get("is_admin") or getattr(request.state, "is_admin", False)):

        raise HTTPException(status_code=403, detail="Administrator access required")

    return user





def _get_user_type(request: Request) -> str:

    value = request.session.get("user_type")
    if not value:
        value = getattr(request.state, "user_type", None)
        if not value:
            current = getattr(request.state, "current_user", None)
            if isinstance(current, dict):
                value = current.get("user_type")

    normalized = _determine_user_type(value)

    if request.session.get("session_token"):
        request.session["user_type"] = normalized
    else:
        request.state.user_type = normalized

    return normalized





def _require_desktop_user(request: Request) -> str:

    username = _require_user(request)

    if _get_user_type(request) != "desktop":

        raise HTTPException(status_code=403, detail="Desktop access required")

    return username





def _start_session_for_user(request: Request, user: Dict[str, Any]) -> None:

    request.session.clear()

    request.session["user"] = user["username"]

    request.session["user_id"] = user["id"]

    request.session["is_admin"] = bool(user["is_admin"])
    request.session["is_company_admin"] = bool(user.get("is_company_admin"))

    request.session["display_name"] = user["name"]

    token = user.get("session_token")

    if not token:

        token = user_store.set_session_token(user["id"])

        user["session_token"] = token

    request.session["session_token"] = token

    request.session["user_type"] = user_store.normalize_user_type(user.get("user_type"))

    scope_usernames, _ = _resolve_company_scope(user["username"])

    history_rows = _collect_history_rows(user["username"], scope_usernames, 5)

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







def _resolve_company_scope(username: str) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    scope: List[str] = []
    user_map: Dict[str, Dict[str, Any]] = {}
    seen: Set[str] = set()

    def _normalize_user_type(value: Optional[str]) -> str:
        try:
            return user_store.normalize_user_type(value)
        except ValueError:
            return user_store.DEFAULT_USER_TYPE

    def _add(record: Optional[Dict[str, Any]]) -> None:
        if not record:
            return
        username_value = record.get("username") if isinstance(record, dict) else None
        if not username_value:
            return
        candidate = str(username_value).strip()
        if not candidate:
            return
        normalized = dict(record)
        normalized["user_type"] = _normalize_user_type(record.get("user_type") if isinstance(record, dict) else None)
        normalized["name"] = normalized.get("name") or ""
        normalized["is_active"] = bool(normalized.get("is_active"))
        user_map[candidate] = normalized
        if candidate not in seen:
            scope.append(candidate)
            seen.add(candidate)

    base = user_store.get_user_by_username(username)
    if base:
        _add(base)
        company_id = base.get("company_id")
        members: List[Dict[str, Any]] = []
        if company_id:
            try:
                members = user_store.list_users(include_disabled=True, company_id=company_id)
            except Exception:
                members = []
                log.exception("Failed to list users for company_id=%s", company_id)
        else:
            company_name = str(base.get("company") or "").strip()
            if company_name:
                lowered = company_name.lower()
                try:
                    members = [
                        member
                        for member in user_store.list_users(include_disabled=True)
                        if str(member.get("company") or "").strip().lower() == lowered
                    ]
                except Exception:
                    members = []
                    log.exception("Failed to list users for company '%s'", company_name)
        for member in members:
            _add(member)
    if not scope:
        fallback = {
            "username": username,
            "name": username,
            "user_type": user_store.DEFAULT_USER_TYPE,
            "is_active": True,
        }
        _add(fallback)
    else:
        if username not in seen:
            scope.insert(0, username)
            seen.add(username)
    if scope:
        first = scope[0]
        rest = sorted(scope[1:], key=lambda value: value.lower())
        ordered = [first, *rest]
    else:
        ordered = [username]
    return ordered, user_map


def _collect_history_rows(username: str, scope_usernames: Sequence[str], limit: int) -> List[Dict[str, Any]]:
    try:
        safe_limit = max(1, int(limit or 1))
    except (TypeError, ValueError):
        safe_limit = 1
    allowed = list(dict.fromkeys(scope_usernames or []))
    if username not in allowed:
        allowed.insert(0, username)
    try:
        return history_store.get_history(username, limit=safe_limit, visible_usernames=allowed)
    except Exception:
        log.exception("Failed to load search history for user=%s", username)
        return []


def _annotate_history_rows(rows: Iterable[Dict[str, Any]], user_map: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    annotated: List[Dict[str, Any]] = []
    for row in rows:
        entry = dict(row)
        owner_username = str(entry.get("username") or "").strip()
        if not owner_username:
            entry["owner_username"] = None
            entry["owner_display_name"] = None
            entry["owner_user_type"] = None
            annotated.append(entry)
            continue
        entry["owner_username"] = owner_username
        owner_record = user_map.get(owner_username)
        if owner_record:
            entry["owner_display_name"] = owner_record.get("name") or owner_username
            entry["owner_user_type"] = owner_record.get("user_type") or user_store.DEFAULT_USER_TYPE
        else:
            entry["owner_display_name"] = owner_username
            entry["owner_user_type"] = None
        annotated.append(entry)
    return annotated


def _collect_permit_records(
    username: str,
    query: str,
    limit: int,
    scope_usernames: Sequence[str],
) -> List[Dict[str, Any]]:
    try:
        safe_limit = max(1, int(limit or 20))
    except (TypeError, ValueError):
        safe_limit = 20
    allowed = list(dict.fromkeys(scope_usernames or []))
    if username not in allowed:
        allowed.insert(0, username)
    try:
        return permit_store.search_permits(
            username=username,
            query=query or "",
            limit=safe_limit,
            visible_usernames=allowed,
        )
    except TypeError:
        try:
            return permit_store.search_permits(username, query or "", safe_limit)
        except Exception:
            log.exception("Permit search fallback failed for user=%s", username)
            return []
    except Exception:
        log.exception("Failed to search permits for user=%s", username)
        return []


def _enrich_permit_items(
    items: Iterable[Dict[str, Any]],
    user_map: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for item in items:
        entry = dict(item)
        owner_username = str(entry.get("owner_username") or entry.get("username") or "").strip()
        entry["owner_username"] = owner_username or None
        owner_record = user_map.get(owner_username) if owner_username else None
        if owner_record:
            entry["owner_display_name"] = owner_record.get("name") or owner_username
            entry["owner_user_type"] = owner_record.get("user_type") or user_store.DEFAULT_USER_TYPE
        else:
            entry["owner_display_name"] = owner_username or None
            entry["owner_user_type"] = None
        for field in (
            "desktop_status",
            "desktop_outcome",
            "site_status",
            "site_outcome",
            "site_bituminous",
            "site_sub_base",
            "sample_status",
            "sample_outcome",
        ):
            value = entry.get(field)
            if isinstance(value, str):
                entry[field] = value.strip() or None
            elif value is None:
                entry[field] = None
            else:
                entry[field] = str(value)
        for field in ("desktop_date", "site_date", "sample_date", "created_at", "updated_at"):
            value = entry.get(field)
            if isinstance(value, datetime):
                entry[field] = value.isoformat()
            elif isinstance(value, str):
                entry[field] = value.strip() or None
            elif value is not None:
                entry[field] = str(value)
        enriched.append(entry)
    return enriched


def _get_permit_record(
    username: str,
    permit_ref: str,
    owner_username: Optional[str],
    scope_usernames: Sequence[str],
) -> Optional[Dict[str, Any]]:
    allowed = list(dict.fromkeys(scope_usernames or []))
    if username not in allowed:
        allowed.insert(0, username)
    try:
        return permit_store.get_permit(
            username,
            permit_ref,
            owner_username=owner_username,
            allowed_usernames=allowed,
        )
    except Exception:
        log.exception(
            "Failed to load permit record permit_ref=%s user=%s owner=%s",
            permit_ref,
            username,
            owner_username,
        )
        return None
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


def _graph_send_mail(subject: str, body: str, *, to_address: str) -> bool:
    if not (GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET and GRAPH_SENDER_UPN):
        log.info("Graph mail not configured; skipping sendMail")
        return False
    try:
        token_resp = requests.post(
            f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": GRAPH_CLIENT_ID,
                "client_secret": GRAPH_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=10,
        )
        if not token_resp.ok:
            log.warning(
                "Graph token request failed: status=%s body=%s",
                token_resp.status_code,
                token_resp.text,
            )
            return False
        access_token = token_resp.json().get("access_token")
        if not access_token:
            log.warning("Graph token response missing access_token")
            return False
        send_resp = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{GRAPH_SENDER_UPN}/sendMail",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to_address}}],
                },
                "saveToSentItems": False,
            },
            timeout=10,
        )
        if send_resp.status_code not in {200, 202}:
            log.warning("Graph sendMail failed: status=%s body=%s", send_resp.status_code, send_resp.text)
            return False
        return True
    except Exception:
        log.exception("Graph sendMail error")
        return False


def _send_signup_notification(name: str, email: str, company: str, phone: str) -> bool:
    to_address = (SIGNUP_NOTIFY_EMAIL or "").strip()
    if not to_address:
        log.info("Signup notification skipped: SIGNUP_NOTIFY_EMAIL not set")
        return False
    subject = "New GeoProx signup"
    body = (
        "A new user signed up.\n\n"
        f"Name: {name or 'N/A'}\n"
        f"Email: {email or 'N/A'}\n"
        f"Company: {company or 'N/A'}\n"
        f"Phone: {phone or 'N/A'}\n"
    )
    return _graph_send_mail(subject, body, to_address=to_address)


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


def _parse_optional_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    try:
        return float(stripped)
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
    raw_user_type = user.get("user_type") or user_store.DEFAULT_USER_TYPE
    try:
        normalized_user_type = user_store.normalize_user_type(raw_user_type)
    except ValueError:
        normalized_user_type = user_store.DEFAULT_USER_TYPE
    user_type_label = user_store.USER_TYPES.get(normalized_user_type, normalized_user_type.title())
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
        is_company_admin=bool(user.get("is_company_admin")),
        is_active=bool(user["is_active"]),
        require_password_change=bool(user.get("require_password_change")),
        license_tier=normalized_tier,
        license_label=tier_label,
        user_type=normalized_user_type,
        user_type_label=user_type_label,
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

def _build_site_form_items(form_payload: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    data = form_payload if isinstance(form_payload, dict) else {}
    items: List[Dict[str, str]] = []
    for key, label in SITE_ASSESSMENT_FIELD_LABELS:
        raw = data.get(key)
        if raw is None:
            value = ""
        elif isinstance(raw, str):
            value = raw.strip()
        else:
            value = str(raw)
        items.append({"label": label, "value": value})
    return items



def _get_s3_client_cached():
    global _S3_CLIENT
    if not S3_BUCKET or boto3 is None:
        return None
    if _S3_CLIENT is None:
        try:
            _S3_CLIENT = boto3.client("s3")
        except Exception:
            log.exception("Failed to initialise S3 client for artifacts")
            _S3_CLIENT = None
    return _S3_CLIENT


def _artifact_s3_key_from_relative(relative_path: str) -> Optional[str]:
    if not relative_path:
        return None
    trimmed = relative_path.strip().lstrip("/\\")
    if not trimmed:
        return None
    if S3_ARTIFACT_PREFIX:
        prefix = S3_ARTIFACT_PREFIX.rstrip("/")
        return f"{prefix}/{trimmed}"
    return trimmed


def _persist_artifact(
    relative_path: Path,
    full_path: Path,
    *,
    content_type: Optional[str] = None,
    delete_local: bool = False,
) -> Dict[str, Optional[str]]:
    url = f"/artifacts/{relative_path.as_posix()}"
    s3_key = None
    client = _get_s3_client_cached()
    if client:
        key = _artifact_s3_key_from_relative(relative_path.as_posix())
        if key:
            extra_args = {"ContentType": content_type} if content_type else None
            try:
                client.upload_file(str(full_path), S3_BUCKET, key, ExtraArgs=extra_args)
                s3_key = key
            except Exception:
                log.exception("Failed to upload artifact to S3 key=%s", key)
    if delete_local and s3_key and full_path.exists():
        try:
            full_path.unlink()
        except Exception:
            log.warning("Unable to remove local artifact copy path=%s", full_path)
    return {"url": url, "s3_key": s3_key}


def _relative_artifact_path(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        try:
            relative = candidate.resolve().relative_to(ARTIFACTS_DIR)
            return relative.as_posix()
        except Exception:
            return None
    normalized = text.replace('\\', '/').lstrip('/')
    return normalized or None


def _resolve_artifact_url(primary: Optional[str], s3_key: Optional[str], path_value: Optional[str], relative_value: Optional[str] = None) -> Optional[str]:
    if s3_key:
        signed = _presign_artifact_key(s3_key)
        if signed:
            return signed
    for candidate in (primary, relative_value):
        normalized = _normalize_artifact_link(candidate)
        if normalized:
            return normalized
    if path_value:
        relative = _relative_artifact_path(path_value)
        if relative:
            return f"/artifacts/{relative}"
        normalized = _normalize_artifact_link(path_value)
        if normalized:
            return normalized
    return None


def _normalize_artifact_link(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    trimmed = str(value).strip()
    if not trimmed:
        return None
    lowered = trimmed.lower()
    if lowered.startswith('http://') or lowered.startswith('https://'):
        return trimmed
    if trimmed.startswith('/'):
        return trimmed
    relative = _relative_artifact_path(trimmed)
    if relative:
        return f"/artifacts/{relative}"
    name = Path(trimmed).name
    if not name:
        return None
    return f"/artifacts/{name}"

def _ensure_local_artifact(relative: Optional[str], path_value: Optional[str], s3_key: Optional[str]) -> Optional[Path]:
    rel_value: Optional[str] = None
    if path_value:
        candidate = Path(path_value)
        if candidate.exists():
            return candidate
        rel_value = _relative_artifact_path(path_value)
    if relative:
        rel_value = relative
    target_path: Optional[Path] = None
    if rel_value:
        rel_path = ARTIFACTS_DIR / Path(rel_value)
        if rel_path.exists():
            return rel_path
        target_path = rel_path
    client = _get_s3_client_cached()
    key = s3_key or (_artifact_s3_key_from_relative(rel_value) if rel_value else None)
    if client and key:
        if target_path is None:
            target_path = ARTIFACTS_DIR / Path(Path(key).name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.download_file(S3_BUCKET, key, str(target_path))
            if target_path.exists():
                return target_path
        except Exception:
            log.exception("Failed to download artifact from S3 key=%s", key)
    return target_path if target_path is not None and target_path.exists() else None


def _collect_attachment_assets(attachments: Sequence[Dict[str, Any]]) -> List[Tuple[str, Path]]:
    assets: List[Tuple[str, Path]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        label = item.get('label') or item.get('filename') or 'Attachment'
        local_path = _ensure_local_artifact(
            item.get('relative_path'),
            item.get('path'),
            item.get('s3_key'),
        )
        if local_path and local_path.exists():
            assets.append((label, local_path))
    return assets


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        iso_text = text
        if iso_text.endswith("Z"):
            iso_text = iso_text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(iso_text)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text, fmt)
                    return dt.replace(tzinfo=timezone.utc if fmt != "%Y-%m-%d" else timezone.utc)
                except ValueError:
                    continue
    return None


def _format_ddmmyy(value: Any, include_time: bool = False) -> str:
    dt = _parse_datetime(value)
    if not dt:
        return str(value) if value not in (None, "") else ""
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%d/%m/%y %H:%M" if include_time else "%d/%m/%y")


def _presign_artifact_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    signer = getattr(history_store, '_signed_url', None)
    if not callable(signer):
        return None
    try:
        return signer(str(key))  # type: ignore[arg-type]
    except Exception:
        return None


def _normalize_search_artifacts(artifacts: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(artifacts)

    def pick(*choices: Optional[str]) -> Optional[str]:
        for choice in choices:
            if not choice:
                continue
            normalized = _normalize_artifact_link(choice)
            if normalized:
                return normalized
        return None

    pdf_url = pick(
        _presign_artifact_key(artifacts.get('pdf_key')),
        artifacts.get('pdf_url'),
        artifacts.get('pdf_download_url'),
        artifacts.get('pdf_path'),
    )
    if pdf_url:
        data['pdf_url'] = pdf_url
        data.setdefault('pdf_download_url', pdf_url)

    map_url = pick(
        _presign_artifact_key(artifacts.get('map_key')),
        artifacts.get('map_url'),
        artifacts.get('map_embed_url'),
        artifacts.get('map_html_url'),
        artifacts.get('map_path'),
    )
    if map_url:
        data['map_url'] = map_url
        data.setdefault('map_embed_url', map_url)

    map_html_url = pick(
        artifacts.get('map_html_url'),
        artifacts.get('map_html_path'),
        data.get('map_url'),
    )
    if map_html_url:
        data['map_html_url'] = map_html_url

    map_image_url = pick(
        _presign_artifact_key(artifacts.get('map_image_key')),
        artifacts.get('map_image_url'),
        artifacts.get('map_image_path'),
    )
    if map_image_url:
        data['map_image_url'] = map_image_url

    for path_field in ('pdf_path', 'map_path', 'map_html_path', 'map_image_path'):
        normalized_path = _normalize_artifact_link(artifacts.get(path_field))
        if normalized_path:
            data[path_field] = normalized_path

    return data

def _group_site_attachments(payload: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    if isinstance(payload, dict):
        raw = payload.get('attachments')
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                category = str(item.get('category') or 'general')
                entry = dict(item)
                if not entry.get('relative_path') and entry.get('path'):
                    relative_guess = _relative_artifact_path(entry.get('path'))
                    if relative_guess:
                        entry['relative_path'] = relative_guess
                entry['url'] = _resolve_artifact_url(
                    entry.get('url'),
                    entry.get('s3_key'),
                    entry.get('path'),
                    entry.get('relative_path'),
                )
                entry['uploaded_at_display'] = _format_ddmmyy(entry.get('uploaded_at'), include_time=True)
                groups.setdefault(category, []).append(entry)
        for attachments in groups.values():
            attachments.sort(key=lambda entry: entry.get('uploaded_at') or '', reverse=True)
    return groups

def _group_sample_attachments(payload: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    if isinstance(payload, dict):
        raw = payload.get('attachments')
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                category = str(item.get('category') or 'general')
                entry = dict(item)
                if not entry.get('relative_path') and entry.get('path'):
                    relative_guess = _relative_artifact_path(entry.get('path'))
                    if relative_guess:
                        entry['relative_path'] = relative_guess
                entry['url'] = _resolve_artifact_url(
                    entry.get('url'),
                    entry.get('s3_key'),
                    entry.get('path'),
                    entry.get('relative_path'),
                )
                entry['uploaded_at_display'] = _format_ddmmyy(entry.get('uploaded_at'), include_time=True)
                groups.setdefault(category, []).append(entry)
        for attachments in groups.values():
            attachments.sort(key=lambda entry: entry.get('uploaded_at') or '', reverse=True)
    return groups


def _slugify_segment(value: str, default: str = 'item') -> str:
    raw = (value or '').strip().lower()
    cleaned = ''.join(ch if ch.isalnum() else '-' for ch in raw)
    cleaned = cleaned.strip('-')
    return cleaned or default


def _build_site_result_summary(form_data: Dict[str, Any]) -> Dict[str, str]:
    return {
        'bituminous': (form_data.get('result_bituminous') or '').strip(),
        'sub_base': (form_data.get('result_sub_base') or '').strip(),
    }


def _normalize_site_status(value: Optional[str]) -> str:
    if not value:
        return SITE_ASSESSMENT_STATUS_OPTIONS[-1][0]
    lowered = value.strip().lower()
    alias_map = {
        "wip": "In progress",
        "work in progress": "In progress",
        "in-progress": "In progress",
        "in progress": "In progress",
        "complete": "Completed",
        "completed": "Completed",
        "not-started": "Not started",
    }
    if lowered in alias_map:
        lowered = alias_map[lowered].lower()
    for status_value, status_label in SITE_ASSESSMENT_STATUS_OPTIONS:
        if lowered == status_value.lower() or lowered == status_label.lower():
            return status_value
    return SITE_ASSESSMENT_STATUS_OPTIONS[-1][0]


def _should_generate_site_pdf(site: Dict[str, Any]) -> bool:
    status_value = _normalize_site_status(site.get("status"))
    if status_value != "Completed":
        return False
    payload = site.get("payload")
    if not isinstance(payload, dict):
        return False
    form = payload.get("form")
    if not isinstance(form, dict):
        return False
    if payload.get("pdf_url") or payload.get("pdf_relative_path") or payload.get("pdf_s3_key"):
        return False
    return True


def _generate_site_pdf_payload(permit_ref: str, site: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = site.get("payload")
    if not isinstance(payload, dict):
        return None

    form_data = payload.get("form")
    if not isinstance(form_data, dict):
        return None

    attachments_block = payload.get("attachments")
    attachments: List[Dict[str, Any]]
    if isinstance(attachments_block, list):
        attachments = [dict(item) if isinstance(item, dict) else {"filename": str(item)} for item in attachments_block]
    elif isinstance(attachments_block, dict):
        attachments = []
        for category, items in attachments_block.items():
            if not isinstance(items, list):
                continue
            for item in items:
                entry: Dict[str, Any]
                if isinstance(item, dict):
                    entry = dict(item)
                else:
                    entry = {"filename": str(item)}
                entry.setdefault("category", category)
                attachments.append(entry)
    else:
        attachments = []

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = _build_site_result_summary(form_data)

    site_assets = _collect_attachment_assets(attachments)

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    pdf_path = ARTIFACTS_DIR / f"site-assessment_{permit_ref}_{timestamp}.pdf"
    generate_site_assessment_pdf(
        pdf_path,
        permit_ref=permit_ref,
        form_data=form_data,
        attachments=site_assets,
        logo_path=STATIC_DIR / 'geoprox-logo.png',
    )

    pdf_relative = pdf_path.relative_to(ARTIFACTS_DIR).as_posix()
    pdf_persisted = _persist_artifact(
        Path(pdf_relative),
        pdf_path,
        content_type="application/pdf",
        delete_local=bool(S3_BUCKET),
    )

    next_payload = dict(payload)
    next_payload["form"] = form_data
    next_payload["summary"] = summary
    next_payload["attachments"] = attachments
    next_payload["pdf_path"] = str(pdf_path)
    next_payload["pdf_relative_path"] = pdf_relative
    if pdf_persisted.get("url"):
        next_payload["pdf_url"] = pdf_persisted["url"]
    else:
        next_payload["pdf_url"] = f"/artifacts/{pdf_relative}"
    if pdf_persisted.get("s3_key"):
        next_payload["pdf_s3_key"] = pdf_persisted["s3_key"]

    return next_payload


def _should_generate_sample_pdf(sample: Dict[str, Any]) -> bool:
    status_value = _normalize_sample_status(sample.get("status"))
    if status_value != SAMPLE_TESTING_STATUS_OPTIONS[-1][0]:
        return False
    payload = sample.get("payload")
    if not isinstance(payload, dict):
        return False
    form = payload.get("form")
    if not isinstance(form, dict):
        return False
    if payload.get("pdf_url") or payload.get("pdf_relative_path") or payload.get("pdf_s3_key"):
        return False
    return True


def _generate_sample_pdf_payload(permit_ref: str, sample: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = sample.get("payload")
    if not isinstance(payload, dict):
        return None

    form_data = payload.get("form")
    if not isinstance(form_data, dict):
        return None

    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        attachments = []

    summary = payload.get("summary")
    if not isinstance(summary, dict) or not summary.get("entries"):
        summary = _build_sample_result_summary(form_data)

    sample_assets = _collect_attachment_assets(attachments)

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    pdf_path = ARTIFACTS_DIR / f"sample-testing_{permit_ref}_{timestamp}.pdf"
    generate_sample_testing_pdf(
        pdf_path,
        permit_ref=permit_ref,
        form_data=form_data,
        attachments=sample_assets,
        logo_path=STATIC_DIR / 'geoprox-logo.png',
    )

    pdf_relative = pdf_path.relative_to(ARTIFACTS_DIR).as_posix()
    pdf_persisted = _persist_artifact(
        Path(pdf_relative),
        pdf_path,
        content_type="application/pdf",
        delete_local=bool(S3_BUCKET),
    )

    next_payload = dict(payload)
    next_payload["form"] = form_data
    next_payload["summary"] = summary
    next_payload["attachments"] = attachments
    next_payload["pdf_path"] = str(pdf_path)
    next_payload["pdf_relative_path"] = pdf_relative
    if pdf_persisted.get("url"):
        next_payload["pdf_url"] = pdf_persisted["url"]
    else:
        next_payload["pdf_url"] = f"/artifacts/{pdf_relative}"
    if pdf_persisted.get("s3_key"):
        next_payload["pdf_s3_key"] = pdf_persisted["s3_key"]

    return next_payload

def _build_sample_result_summary(form_data: Dict[str, Any]) -> Dict[str, Any]:
    entries = []
    for key, label in SAMPLE_TESTING_ENTRY_KEYS:
        entry = {
            'label': label,
            'number': (form_data.get(f'{key}_number') or '').strip(),
            'material': (form_data.get(f'{key}_material') or '').strip(),
            'lab_result': (form_data.get(f'{key}_lab_result') or '').strip(),
            'determinants': [],
        }
        for det_key, det_label in SAMPLE_TESTING_DETERMINANTS:
            entry['determinants'].append({
                'label': det_label,
                'present': (form_data.get(f'{key}_{det_key}_present') or '').strip(),
                'concentration': (form_data.get(f'{key}_{det_key}_concentration') or '').strip(),
            })
        entries.append(entry)
    summary = {
        'entries': entries,
        'sampling_date': (form_data.get('sampling_date') or '').strip(),
        'sampled_by': (form_data.get('sampled_by_name') or '').strip(),
        'results_recorded_by': (form_data.get('results_recorded_by') or '').strip(),
    }
    return summary


def _normalize_sample_status(value: Optional[str]) -> str:
    if not value:
        return SAMPLE_TESTING_STATUS_DEFAULT
    lowered = value.strip().lower()
    for status_value, status_label in SAMPLE_TESTING_STATUS_OPTIONS:
        if lowered == status_value.lower() or lowered == status_label.lower():
            return status_label
    return SAMPLE_TESTING_STATUS_DEFAULT


def _summarize_site_outcome(summary: Dict[str, str]) -> Optional[str]:
    bituminous = summary.get('bituminous') or ''
    sub_base = summary.get('sub_base') or ''
    if not bituminous and not sub_base:
        return None
    bituminous = bituminous or '-'
    sub_base = sub_base or '-'
    return f"Bituminous: {bituminous} | Sub-base: {sub_base}"

def _summarize_sample_outcome(summary: Dict[str, Any]) -> Optional[str]:
    entries = summary.get('entries') if isinstance(summary.get('entries'), list) else []
    highlights = []
    for entry in entries:
        label = entry.get('label') or ''
        lab_result = (entry.get('lab_result') or '').strip()
        if label or lab_result:
            highlights.append(f"{label}: {lab_result or '-'}")
    if not highlights:
        return None
    return ' | '.join(highlights)


async def _save_site_attachment(permit_ref: str, category: str, upload: UploadFile) -> Dict[str, str]:
    filename = (upload.filename or '').strip()
    if not filename:
        return {}
    data = await upload.read()
    try:
        await upload.close()
    except Exception:
        pass
    if not data:
        return {}
    if len(data) > MAX_SITE_ATTACHMENT_SIZE:
        raise ValueError(f"{filename} is larger than the {MAX_SITE_ATTACHMENT_SIZE // (1024 * 1024)} MB limit.")
    content_type = (upload.content_type or '').lower()
    suffix = SITE_ASSESSMENT_ALLOWED_IMAGE_MIME_MAP.get(content_type)
    if not suffix:
        guessed = Path(filename).suffix.lower()
        if guessed in SITE_ASSESSMENT_ALLOWED_IMAGE_SUFFIXES:
            suffix = guessed
        else:
            guessed = mimetypes.guess_extension(content_type or '') or ''
            guessed = guessed.lower()
            if guessed in SITE_ASSESSMENT_ALLOWED_IMAGE_SUFFIXES:
                suffix = guessed
    if not suffix:
        raise ValueError(f"Unsupported file type for {filename}. Please upload an image file.")
    safe_permit = _slugify_segment(permit_ref, 'permit')
    safe_category = _slugify_segment(category, 'attachment')
    timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%S')
    unique = uuid4().hex[:8]
    relative_path = Path('site-assessments') / safe_permit / safe_category / f"{timestamp}_{unique}{suffix}"
    full_path = ARTIFACTS_DIR / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(data)
    label = SITE_ASSESSMENT_ATTACHMENT_LABELS.get(category, category.title())
    content_type = content_type or mimetypes.guess_type(filename)[0] or 'image/*'
    persisted = _persist_artifact(
        relative_path,
        full_path,
        content_type=content_type,
        delete_local=bool(S3_BUCKET),
    )
    return {
        'category': category,
        'label': label,
        'filename': filename,
        'content_type': content_type,
        'path': str(full_path),
        'relative_path': relative_path.as_posix(),
        'url': persisted.get('url') or f"/artifacts/{relative_path.as_posix()}",
        's3_key': persisted.get('s3_key'),
        'uploaded_at': datetime.utcnow().isoformat() + 'Z',
    }



async def _save_sample_attachment(permit_ref: str, category: str, upload: UploadFile) -> Dict[str, str]:
    filename = (upload.filename or '').strip()
    if not filename:
        return {}
    data = await upload.read()
    try:
        await upload.close()
    except Exception:
        pass
    if not data:
        return {}
    if len(data) > MAX_SITE_ATTACHMENT_SIZE:
        raise ValueError(f"{filename} is larger than the {MAX_SITE_ATTACHMENT_SIZE // (1024 * 1024)} MB limit.")
    content_type = (upload.content_type or '').lower()
    suffix = SITE_ASSESSMENT_ALLOWED_IMAGE_MIME_MAP.get(content_type)
    if not suffix:
        guessed = Path(filename).suffix.lower()
        if guessed in SITE_ASSESSMENT_ALLOWED_IMAGE_SUFFIXES:
            suffix = guessed
        else:
            guessed = mimetypes.guess_extension(content_type or '') or ''
            guessed = guessed.lower()
            if guessed in SITE_ASSESSMENT_ALLOWED_IMAGE_SUFFIXES:
                suffix = guessed
    if not suffix:
        raise ValueError(f"Unsupported file type for {filename}. Please upload an image file.")
    safe_permit = _slugify_segment(permit_ref, 'permit')
    safe_category = _slugify_segment(category, 'attachment')
    timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%S')
    unique = uuid4().hex[:8]
    relative_path = Path('sample-testing') / safe_permit / safe_category / f"{timestamp}_{unique}{suffix}"
    full_path = ARTIFACTS_DIR / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(data)
    label = SAMPLE_TESTING_ATTACHMENT_LABELS.get(category, category.title())
    content_type = content_type or mimetypes.guess_type(filename)[0] or 'image/*'
    persisted = _persist_artifact(
        relative_path,
        full_path,
        content_type=content_type,
        delete_local=bool(S3_BUCKET),
    )
    return {
        'category': category,
        'label': label,
        'filename': filename,
        'content_type': content_type,
        'path': str(full_path),
        'relative_path': relative_path.as_posix(),
        'url': persisted.get('url') or f"/artifacts/{relative_path.as_posix()}",
        's3_key': persisted.get('s3_key'),
        'uploaded_at': datetime.utcnow().isoformat() + 'Z',
    }





def _permit_to_response(record: Dict[str, Any], owner_display_name: Optional[str] = None) -> PermitRecordResp:
    location = record.get("location") or {}
    desktop = record.get("desktop") or {}
    site = record.get("site") or {}
    sample = record.get("sample") or {}

    def _to_iso(value: Any) -> Optional[str]:
        if isinstance(value, datetime):
            return value.isoformat()
        if value is None:
            return None
        return str(value)

    desktop_summary = desktop.get("summary") if isinstance(desktop.get("summary"), dict) else None
    site_payload = site.get("payload") if isinstance(site.get("payload"), dict) else None
    site_summary = site.get("summary") if isinstance(site.get("summary"), dict) else None
    if not site_summary and isinstance(site_payload, dict):
        summary_candidate = site_payload.get("summary")
        if isinstance(summary_candidate, dict):
            site_summary = summary_candidate
    sample_payload = sample.get("payload") if isinstance(sample.get("payload"), dict) else None
    sample_summary = sample.get("summary") if isinstance(sample.get("summary"), dict) else None
    if not sample_summary and isinstance(sample_payload, dict):
        summary_candidate = sample_payload.get("summary")
        if isinstance(summary_candidate, dict):
            sample_summary = summary_candidate
    search_payload_raw = record.get("search_result")
    search_payload = search_payload_raw if isinstance(search_payload_raw, dict) else None
    if search_payload:
        search_payload = dict(search_payload)
        artifacts = search_payload.get("artifacts")
        if isinstance(artifacts, dict):
            search_payload["artifacts"] = _normalize_search_artifacts(artifacts)
    desktop_notes = desktop.get("notes") if isinstance(desktop.get("notes"), str) else None
    site_notes = site.get("notes") if isinstance(site.get("notes"), str) else None
    sample_notes = sample.get("notes") if isinstance(sample.get("notes"), str) else None

    owner_username_raw = record.get("username")
    owner_username = str(owner_username_raw).strip() if owner_username_raw else None
    owner_display = owner_display_name or owner_username

    return PermitRecordResp(
        permit_ref=str(record.get("permit_ref", "")),
        created_at=_to_iso(record.get("created_at")),
        updated_at=_to_iso(record.get("updated_at")),
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
            summary=site_summary,
            payload=site_payload,
        ),
        sample=PermitStage(
            status=str(sample.get("status") or SAMPLE_TESTING_STATUS_DEFAULT),
            outcome=sample.get("outcome"),
            notes=sample_notes,
            summary=sample_summary,
            payload=sample_payload,
        ),
        owner_username=owner_username,
        owner_display_name=owner_display,
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
        user["session_token"] = user_store.set_session_token(user["id"])
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

    notified = _send_signup_notification(
        name=data["full_name"],
        email=data["email"],
        company=data["company_name"],
        phone=data["phone"],
    )
    if not notified:
        log.info("Signup notification not sent for %s", username)

    user_record["session_token"] = user_store.set_session_token(user_record["id"])
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
    username = request.session.get("user")
    token = request.session.get("session_token")
    if username:
        user_store.clear_session_token(username, expected_token=token)
    request.session.clear()
    response = RedirectResponse(url="/", status_code=303)
    return response


@app.post("/api/mobile/auth/login", response_model=MobileAuthResponse)
async def mobile_auth_login(request: Request, payload: MobileAuthRequest) -> MobileAuthResponse:
    username = (payload.username or "").strip()
    if not username or not payload.password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    if "@" in username:
        username = username.lower()
    user = user_store.verify_credentials(username, payload.password, include_disabled=True)
    if not user:
        log.info("Mobile login failed for %s", username)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="Account disabled")
    if user.get("require_password_change"):
        raise HTTPException(status_code=403, detail="Password change required before mobile access")
    response = _issue_mobile_tokens(user)
    log.info("Mobile login success for %s via %s", username, getattr(request.client, "host", "-"))
    return response


@app.post("/api/mobile/auth/refresh", response_model=MobileAuthResponse)
async def mobile_auth_refresh(payload: MobileRefreshRequest) -> MobileAuthResponse:
    token = (payload.refresh_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Refresh token is required")
    try:
        data = decode_refresh_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc
    username = data.get("sub")
    session_token = data.get("stk")
    if not isinstance(username, str) or not isinstance(session_token, str):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = user_store.get_user_by_username(username)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="Authentication required")
    stored_token = user.get("session_token")
    if not stored_token or stored_token != session_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    return _issue_mobile_tokens(user)


@app.post("/api/mobile/auth/logout", status_code=204)
async def mobile_auth_logout(request: Request) -> Response:
    bearer = _extract_bearer_token(request)
    if not bearer:
        return Response(status_code=204)
    try:
        data = decode_access_token(bearer)
    except TokenError:
        return Response(status_code=204)
    username = data.get("sub")
    session_token = data.get("stk")
    if not isinstance(username, str) or not isinstance(session_token, str):
        return Response(status_code=204)
    log.info("Mobile logout for %s", username)
    return Response(status_code=204)


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
    updated["session_token"] = user_store.set_session_token(updated["id"])
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
                    updated["session_token"] = user_store.set_session_token(updated["id"])
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
def _issue_mobile_tokens(user: Dict[str, Any]) -> MobileAuthResponse:
    session_token = user.get("session_token")
    if not session_token:
        session_token = user_store.set_session_token(user["id"])
        user["session_token"] = session_token
    scope = _build_user_scope(user)
    access_token, access_exp = create_access_token(
        username=user["username"],
        session_token=session_token,
        scope=scope,
    )
    refresh_token, refresh_exp = create_refresh_token(
        username=user["username"],
        session_token=session_token,
        scope=scope,
    )
    now = int(time.time())
    return MobileAuthResponse(
        access_token=access_token,
        expires_in=max(int(access_exp - now), 0),
        refresh_token=refresh_token,
        refresh_expires_in=max(int(refresh_exp - now), 0),
        scope=scope,
    )


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
    is_company_admin: bool
    is_active: bool
    require_password_change: bool
    license_tier: str
    license_label: str
    user_type: str
    user_type_label: str
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
    is_company_admin: bool = False
    is_active: bool = True
    require_password_change: bool = True
    license_tier: str = Field(default=user_store.DEFAULT_LICENSE_TIER)
    user_type: str = Field(default=user_store.DEFAULT_USER_TYPE)


class AdminUserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    email: Optional[str] = Field(default=None, max_length=256)
    company: Optional[str] = Field(default=None, max_length=256)
    company_id: Optional[int] = None
    company_number: Optional[str] = Field(default=None, max_length=64)
    phone: Optional[str] = Field(default=None, max_length=64)
    is_admin: Optional[bool] = None
    is_company_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    require_password_change: Optional[bool] = None
    license_tier: Optional[str] = None
    user_type: Optional[str] = None


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
    sample: PermitStage
    owner_username: Optional[str] = None
    owner_display_name: Optional[str] = None
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


class PermitSampleUpdateReq(BaseModel):
    status: str = Field(default=SAMPLE_TESTING_STATUS_DEFAULT, min_length=1, max_length=120)
    outcome: Optional[str] = None
    notes: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

    class Config:
        extra = "forbid"

class PermitSearchItem(BaseModel):
    permit_ref: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    desktop_status: Optional[str] = None
    desktop_outcome: Optional[str] = None
    desktop_date: Optional[str] = None
    site_status: Optional[str] = None
    site_outcome: Optional[str] = None
    site_bituminous: Optional[str] = None
    site_sub_base: Optional[str] = None
    site_date: Optional[str] = None
    sample_status: Optional[str] = None
    sample_outcome: Optional[str] = None
    sample_date: Optional[str] = None
    owner_username: Optional[str] = None
    owner_display_name: Optional[str] = None

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
    scope_usernames, user_map = _resolve_company_scope(username)
    rows = _collect_history_rows(username, scope_usernames, 20)
    annotated = _annotate_history_rows(rows, user_map)
    return {"history": annotated}



@app.get("/dashboard", response_class=HTMLResponse)

async def dashboard_page(request: Request) -> HTMLResponse:

    username = _require_user(request)

    user_type = _get_user_type(request)

    display_name = request.session.get("display_name") or username

    user_type_label = user_store.USER_TYPES.get(user_type, user_type.title())

    return templates.TemplateResponse(

        "dashboard.html",

        {

            "request": request,

            "user": username,

            "display_name": display_name,

            "is_admin": bool(request.session.get("is_admin")),
            "is_company_admin": bool(request.session.get("is_company_admin")),

            "user_type": user_type,

            "user_type_label": user_type_label,

            "allow_desktop": user_type == "desktop",

        },

    )

@app.get("/permits", response_class=HTMLResponse)

async def permits_page(request: Request) -> HTMLResponse:

    username = _require_user(request)

    user_type = _get_user_type(request)

    user_type_label = user_store.USER_TYPES.get(user_type, user_type.title())

    flashes = _consume_flashes(request)

    scope_usernames, user_map = _resolve_company_scope(username)

    permit_records = _collect_permit_records(username, "", 20, scope_usernames)

    annotated_results = _enrich_permit_items(permit_records, user_map)

    field_names = PermitSearchItem.model_fields.keys()

    initial_results: List[Dict[str, Any]] = [

        PermitSearchItem(**{field: entry.get(field) for field in field_names}).model_dump()

        for entry in annotated_results

    ]

    return templates.TemplateResponse(

        "permits.html",

        {

            "request": request,

            "user": username,

            "display_name": request.session.get("display_name") or username,

            "initial_results": initial_results,

            "flashes": flashes,

            "has_company_scope": len(scope_usernames) > 1,

            "visible_usernames": scope_usernames,

            "user_type": user_type,

            "user_type_label": user_type_label,

            "allow_desktop": user_type == "desktop",

        },

    )

@app.get("/permits/{permit_ref}/view", response_class=HTMLResponse)
async def permit_detail_page(request: Request, permit_ref: str) -> HTMLResponse:
    username = _require_user(request)
    user_type = _get_user_type(request)
    scope_usernames, user_map = _resolve_company_scope(username)
    owner_param_raw = request.query_params.get("owner")
    owner_param = owner_param_raw.strip() or None if owner_param_raw else None
    if owner_param and owner_param not in scope_usernames:
        raise HTTPException(status_code=404, detail="Permit not found")
    record = _get_permit_record(username, permit_ref, owner_param, scope_usernames)
    if not record:
        raise HTTPException(status_code=404, detail="Permit not found")
    owner_username = record.get("username")
    owner_display = None
    if owner_username:
        owner_record = user_map.get(owner_username)
        if owner_record and owner_record.get("name"):
            owner_display = owner_record.get("name")
        else:
            owner_display = owner_username
    permit = _permit_to_response(record, owner_display_name=owner_display)
    flashes = _consume_flashes(request)
    site_payload = permit.site.payload or {}
    if not isinstance(site_payload, dict):
        site_payload = {}
    form_payload = site_payload.get("form") if isinstance(site_payload.get("form"), dict) else {}
    site_form_items = _build_site_form_items(form_payload)
    site_pdf_url = _resolve_artifact_url(
        site_payload.get("pdf_url"),
        site_payload.get("pdf_s3_key"),
        site_payload.get("pdf_path"),
        site_payload.get("pdf_relative_path"),
    )
    site_summary = permit.site.summary if isinstance(permit.site.summary, dict) else {}
    if not site_summary and form_payload:
        site_summary = _build_site_result_summary(form_payload)
    attachments_grouped = _group_site_attachments(site_payload)
    raw_sample_payload = permit.sample.payload if isinstance(permit.sample.payload, dict) else {}
    sample_payload: Dict[str, Any] = dict(raw_sample_payload)

    attachments_block = sample_payload.get("attachments")
    if isinstance(attachments_block, dict):
        attachments_list: List[Dict[str, Any]] = []
        for category, items in attachments_block.items():
            if not isinstance(items, list):
                continue
            for item in items:
                entry: Dict[str, Any]
                if isinstance(item, dict):
                    entry = dict(item)
                else:
                    entry = {"filename": str(item)}
                entry.setdefault("category", category)
                attachments_list.append(entry)
        sample_payload["attachments"] = attachments_list
    elif not isinstance(attachments_block, list):
        sample_payload["attachments"] = []

    sample_form = sample_payload.get("form") if isinstance(sample_payload.get("form"), dict) else {}
    sample_summary = permit.sample.summary if isinstance(permit.sample.summary, dict) else {}
    if not isinstance(sample_summary, dict) or not sample_summary.get("entries"):
        if sample_form:
            sample_summary = _build_sample_result_summary(sample_form)
        else:
            sample_summary = {}
    sample_payload["summary"] = sample_summary
    sample_pdf_url = _resolve_artifact_url(
        sample_payload.get("pdf_url"),
        sample_payload.get("pdf_s3_key"),
        sample_payload.get("pdf_path"),
        sample_payload.get("pdf_relative_path"),
    )
    sample_attachments_grouped = _group_sample_attachments(sample_payload)
    sample_outcome_summary = _summarize_sample_outcome(sample_summary) if sample_summary else None
    search_payload = permit.search_result if isinstance(permit.search_result, dict) else {}
    desktop_details = []
    if isinstance(search_payload.get("details_100m"), list):
        for row in search_payload.get("details_100m"):
            if not isinstance(row, dict):
                continue
            desktop_details.append({
                "distance": row.get("distance_m"),
                "category": row.get("category"),
                "name": row.get("name") or "(unnamed)",
                "address": row.get("address") or "",
                "lat": row.get("lat"),
                "lon": row.get("lon"),
            })
    created_at_display = _format_ddmmyy(record.get("created_at"), include_time=True)
    updated_at_display = _format_ddmmyy(record.get("updated_at"), include_time=True)
    return templates.TemplateResponse(
        "permit_detail.html",
        {
            "request": request,
            "user": username,
            "display_name": request.session.get("display_name") or username,
            "permit": permit,
            "site_payload": site_payload,
            "site_form_items": site_form_items,
            "site_form": form_payload or {},
            "has_company_scope": len(scope_usernames) > 1,
            "visible_usernames": scope_usernames,
            "owner_username": permit.owner_username,
            "owner_display_name": permit.owner_display_name,
            "detail_fields": SITE_ASSESSMENT_DETAIL_FIELDS,
            "question_meta": SITE_ASSESSMENT_QUESTIONS,
            "question_sections": SITE_ASSESSMENT_QUESTION_SECTIONS,
            "result_meta": SITE_ASSESSMENT_RESULT_FIELDS,
            "site_pdf_url": site_pdf_url,
            "site_summary": site_summary,
            "attachment_categories": SITE_ASSESSMENT_ATTACHMENT_CATEGORIES,
            "attachments_grouped": attachments_grouped,
            "sample_payload": sample_payload,
            "sample_form": sample_form or {},
            "sample_summary": sample_summary,
            "sample_outcome_summary": sample_outcome_summary,
            "sample_pdf_url": sample_pdf_url,
            "sample_attachment_categories": SAMPLE_TESTING_ATTACHMENT_CATEGORIES,
            "sample_attachments_grouped": sample_attachments_grouped,
            "sample_detail_fields": SAMPLE_TESTING_FIELD_LABELS,
            "sample_entry_keys": SAMPLE_TESTING_ENTRY_KEYS,
            "sample_determinants": SAMPLE_TESTING_DETERMINANTS,
            "sample_status_options": SAMPLE_TESTING_STATUS_OPTIONS,
            "desktop_details": desktop_details,
            "created_at_display": created_at_display,
            "updated_at_display": updated_at_display,
            "user_type": user_type,
            "allow_desktop": user_type == "desktop",
            "flashes": flashes,
        },
    )


@app.get("/permits/{permit_ref}/site-assessment", response_class=HTMLResponse)
async def site_assessment_page(request: Request, permit_ref: str) -> HTMLResponse:
    username = _require_user(request)
    scope_usernames, user_map = _resolve_company_scope(username)
    owner_param = request.query_params.get("owner")
    if owner_param:
        owner_param = owner_param.strip() or None
    if owner_param and owner_param not in scope_usernames:
        raise HTTPException(status_code=404, detail="Permit not found")
    record = permit_store.get_permit(
        username,
        permit_ref,
        owner_username=owner_param,
        allowed_usernames=scope_usernames,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Permit not found")
    owner_username = record.get("username")
    owner_record = user_map.get(owner_username) if owner_username else None
    owner_display = None
    if owner_record and owner_record.get("name"):
        owner_display = owner_record.get("name")
    elif owner_username:
        owner_display = owner_username
    permit = _permit_to_response(record, owner_display_name=owner_display)
    flashes = _consume_flashes(request)
    site_payload = permit.site.payload or {}
    if not isinstance(site_payload, dict):
        site_payload = {}
    form_defaults = site_payload.get("form") if isinstance(site_payload.get("form"), dict) else {}
    form_defaults = dict(form_defaults or {})
    attachments_grouped = _group_site_attachments(site_payload)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if not form_defaults.get("assessment_date"):
        form_defaults["assessment_date"] = today
    if not form_defaults.get("permit_number"):
        form_defaults["permit_number"] = permit.permit_ref
    surface_locations_raw = form_defaults.get("surface_locations")
    normalized_surface_locations: List[str] = []
    if isinstance(surface_locations_raw, list):
        for value in surface_locations_raw:
            if not isinstance(value, str):
                continue
            stripped = value.strip()
            if not stripped:
                continue
            match = next(
                (option for option in SITE_ASSESSMENT_SURFACE_OPTIONS if stripped.lower() == option.lower()),
                None,
            )
            if match and match not in normalized_surface_locations:
                normalized_surface_locations.append(match)

    surface_value = form_defaults.get("surface_location")
    if not normalized_surface_locations and isinstance(surface_value, str):
        parts = [part.strip() for part in surface_value.split(",") if part.strip()]
        for part in parts:
            lowered = part.lower()
            match = next(
                (
                    option
                    for option in SITE_ASSESSMENT_SURFACE_OPTIONS
                    if lowered == option.lower() or (option == "Other" and lowered.startswith("other"))
                ),
                None,
            )
            if match and match not in normalized_surface_locations:
                normalized_surface_locations.append(match)

    form_defaults["surface_locations"] = normalized_surface_locations

    if "surface_location_other" not in form_defaults:
        other_text = ""
        if isinstance(surface_value, str) and "Other - " in surface_value:
            other_text = surface_value.split("Other - ", 1)[-1].strip()
        form_defaults["surface_location_other"] = other_text
    site_pdf_url = _resolve_artifact_url(
        site_payload.get("pdf_url"),
        site_payload.get("pdf_s3_key"),
        site_payload.get("pdf_path"),
        site_payload.get("pdf_relative_path"),
    )
    return templates.TemplateResponse(
        "site_assessment.html",
        {
            "request": request,
            "user": username,
            "display_name": request.session.get("display_name") or username,
            "permit": permit,
            "form_defaults": form_defaults,
            "today": today,
            "flashes": flashes,
            "site_status": permit.site.status or "Not started",
            "site_notes": permit.site.notes or "",
            "status_options": SITE_ASSESSMENT_STATUS_OPTIONS,
            "location_options": SITE_ASSESSMENT_LOCATION_OPTIONS,
            "works_type_options": SITE_ASSESSMENT_WORKS_TYPE_OPTIONS,
            "surface_options": SITE_ASSESSMENT_SURFACE_OPTIONS,
            "question_meta": SITE_ASSESSMENT_QUESTIONS,
            "result_meta": SITE_ASSESSMENT_RESULT_FIELDS,
            "result_choices": SITE_ASSESSMENT_RESULT_CHOICES,
            "yes_no_choices": SITE_ASSESSMENT_YES_NO_CHOICES,
            "yes_no_na_choices": SITE_ASSESSMENT_YES_NO_NA_CHOICES,
            "yes_no_na_keys": SITE_ASSESSMENT_YES_NO_NA_KEYS,
            "site_pdf_url": site_pdf_url,
            "question_sections": SITE_ASSESSMENT_QUESTION_SECTIONS,
            "attachment_categories": SITE_ASSESSMENT_ATTACHMENT_CATEGORIES,
            "attachments_grouped": attachments_grouped,
        },
    )


@app.post("/permits/{permit_ref}/site-assessment", response_class=HTMLResponse)
async def site_assessment_submit(request: Request, permit_ref: str) -> Response:
    username = _require_user(request)
    scope_usernames, _ = _resolve_company_scope(username)
    record = permit_store.get_permit(username, permit_ref, allowed_usernames=scope_usernames)
    if not record:
        raise HTTPException(status_code=404, detail="Permit not found")

    form = await request.form()

    def _clean(key: str) -> str:
        return (form.get(key) or "").strip()

    def _select(key: str, options: List[str]) -> str:
        value = _clean(key)
        if not value:
            return ""
        value_lower = value.lower()
        for option in options:
            if value_lower == option.lower():
                return option
        return ""

    status = _select("site_status", [value for value, _ in SITE_ASSESSMENT_STATUS_OPTIONS]) or "Completed"
    status = _normalize_site_status(status)
    notes = _clean("site_notes") or None

    works_type = _select("works_type", SITE_ASSESSMENT_WORKS_TYPE_OPTIONS)
    surface_other = _clean("surface_location_other")
    raw_surface_values: List[str] = []
    if hasattr(form, "getlist"):
        raw_surface_values = [value for value in form.getlist("surface_locations") if isinstance(value, str)]
    else:
        single_value = form.get("surface_locations")
        if isinstance(single_value, str):
            raw_surface_values = [part.strip() for part in single_value.split(",") if part.strip()]

    selected_surface_options: List[str] = []
    for value in raw_surface_values:
        candidate = value.strip()
        if not candidate:
            continue
        match = next(
            (option for option in SITE_ASSESSMENT_SURFACE_OPTIONS if candidate.lower() == option.lower()),
            None,
        )
        if match and match not in selected_surface_options:
            selected_surface_options.append(match)

    surface_display_parts: List[str] = []
    for option in selected_surface_options:
        if option == "Other":
            if surface_other:
                surface_display_parts.append(f"Other - {surface_other}")
            else:
                surface_display_parts.append("Other")
        else:
            surface_display_parts.append(option)
    if not surface_display_parts and surface_other:
        surface_display_parts.append(surface_other)
    surface_location_display = ", ".join(surface_display_parts)

    today = datetime.utcnow().strftime("%Y-%m-%d")

    form_data = {
        "utility_type": _clean("utility_type"),
        "assessment_date": _clean("assessment_date") or today,
        "permit_number": _clean("permit_number") or permit_ref,
        "excavation_site_number": _clean("excavation_site_number"),
        "site_address": _clean("site_address"),
        "highway_authority": _clean("highway_authority"),
        "works_type": works_type,
        "surface_locations": selected_surface_options,
        "surface_location": surface_location_display,
        "surface_location_other": surface_other,
        "what_three_words": _clean("what_three_words"),
        "q1_asbestos": _select("q1_asbestos", SITE_ASSESSMENT_YES_NO_CHOICES),
        "q2_binder_shiny": _select("q2_binder_shiny", SITE_ASSESSMENT_YES_NO_CHOICES),
        "q3_spray_pak": _select("q3_spray_pak", SITE_ASSESSMENT_YES_NO_NA_CHOICES),
        "q4_soil_colour": _select("q4_soil_colour", SITE_ASSESSMENT_YES_NO_CHOICES),
        "q5_water_sheen": _select("q5_water_sheen", SITE_ASSESSMENT_YES_NO_CHOICES),
        "q6_pungent_odour": _select("q6_pungent_odour", SITE_ASSESSMENT_YES_NO_CHOICES),
        "q7_litmus_change": _select("q7_litmus_change", SITE_ASSESSMENT_YES_NO_NA_CHOICES),
        "result_bituminous": _select("result_bituminous", SITE_ASSESSMENT_RESULT_CHOICES),
        "result_sub_base": _select("result_sub_base", SITE_ASSESSMENT_RESULT_CHOICES),
        "assessor_name": _clean("assessor_name"),
        "site_notes": notes or "",
    }

    summary = _build_site_result_summary(form_data)
    outcome = _summarize_site_outcome(summary)

    existing_payload = record.get("site", {}).get("payload") if isinstance(record.get("site"), dict) else None
    existing_attachments: List[Dict[str, Any]] = []
    if isinstance(existing_payload, dict):
        raw_attachments = existing_payload.get("attachments")
        if isinstance(raw_attachments, list):
            for item in raw_attachments:
                if isinstance(item, dict):
                    existing_attachments.append(item)

    attachments: List[Dict[str, Any]] = list(existing_attachments)
    attachment_paths = {att.get("path") for att in attachments if isinstance(att.get("path"), str)}

    if hasattr(form, "getlist"):
        for category, _label in SITE_ASSESSMENT_ATTACHMENT_CATEGORIES:
            uploads = form.getlist(f"attachment_{category}")
            for upload in uploads:
                if not isinstance(upload, UploadFile):
                    continue
                if not upload.filename:
                    continue
                try:
                    saved = await _save_site_attachment(permit_ref, category, upload)
                except ValueError as exc:
                    _add_flash(request, str(exc), "error")
                    return RedirectResponse(url=f"/permits/{permit_ref}/site-assessment", status_code=303)
                except Exception:
                    log.exception(
                        "Failed to save site attachment permit=%s category=%s filename=%s",
                        permit_ref,
                        category,
                        upload.filename,
                    )
                    _add_flash(request, f"Failed to save attachment '{upload.filename}'.", "error")
                    return RedirectResponse(url=f"/permits/{permit_ref}/site-assessment", status_code=303)
                if saved:
                    path_value = saved.get("path")
                    if path_value and path_value not in attachment_paths:
                        attachment_paths.add(path_value)
                        attachments.append(saved)
    else:
        log.warning("Form data missing getlist() support; skipping attachments for permit %s", permit_ref)

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if not attachment.get('relative_path') and attachment.get('path'):
            rel_guess = _relative_artifact_path(attachment.get('path'))
            if rel_guess:
                attachment['relative_path'] = rel_guess
        if S3_BUCKET and not attachment.get('s3_key'):
            rel = attachment.get('relative_path')
            path_value = attachment.get('path')
            try:
                if rel and path_value and Path(path_value).exists():
                    persisted_attachment = _persist_artifact(Path(rel), Path(path_value), content_type=attachment.get('content_type'))
                    if persisted_attachment.get('s3_key'):
                        attachment['s3_key'] = persisted_attachment['s3_key']
                    if persisted_attachment.get('url'):
                        attachment['url'] = persisted_attachment['url']
            except Exception:
                log.exception("Failed to sync site attachment to S3 path=%s", attachment.get('path'))

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    pdf_path = ARTIFACTS_DIR / f"site-assessment_{permit_ref}_{timestamp}.pdf"
    site_assets = _collect_attachment_assets(attachments)
    generate_site_assessment_pdf(
        pdf_path,
        permit_ref=permit_ref,
        form_data=form_data,
        attachments=site_assets,
        logo_path=STATIC_DIR / 'geoprox-logo.png',
    )

    pdf_relative = pdf_path.relative_to(ARTIFACTS_DIR).as_posix()
    pdf_persisted = _persist_artifact(
        Path(pdf_relative),
        pdf_path,
        content_type="application/pdf",
        delete_local=bool(S3_BUCKET),
    )

    payload: Dict[str, Any] = {
        "form": form_data,
        "summary": summary,
        "pdf_path": str(pdf_path),
        "pdf_relative_path": pdf_relative,
        "pdf_url": pdf_persisted.get("url") or f"/artifacts/{pdf_relative}",
        "pdf_s3_key": pdf_persisted.get("s3_key"),
        "attachments": attachments,
    }

    permit_store.update_site_assessment(
        username=username,
        permit_ref=permit_ref,
        status=status,
        outcome=outcome,
        notes=notes,
        payload=payload,
        allowed_usernames=scope_usernames,
    )
    _add_flash(request, "Site assessment saved.", "success")
    return RedirectResponse(url=f"/permits/{permit_ref}/view", status_code=303)



@app.get("/permits/{permit_ref}/sample-testing", response_class=HTMLResponse)
async def sample_testing_page(request: Request, permit_ref: str) -> HTMLResponse:
    username = _require_user(request)
    scope_usernames, user_map = _resolve_company_scope(username)
    owner_param = request.query_params.get("owner")
    if owner_param:
        owner_param = owner_param.strip() or None
    if owner_param and owner_param not in scope_usernames:
        raise HTTPException(status_code=404, detail="Permit not found")
    record = permit_store.get_permit(
        username,
        permit_ref,
        owner_username=owner_param,
        allowed_usernames=scope_usernames,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Permit not found")
    owner_username = record.get("username")
    owner_record = user_map.get(owner_username) if owner_username else None
    owner_display = None
    if owner_record and owner_record.get("name"):
        owner_display = owner_record.get("name")
    elif owner_username:
        owner_display = owner_username
    permit = _permit_to_response(record, owner_display_name=owner_display)
    flashes = _consume_flashes(request)

    sample_payload = permit.sample.payload or {}
    if not isinstance(sample_payload, dict):
        sample_payload = {}
    form_defaults = sample_payload.get("form") if isinstance(sample_payload.get("form"), dict) else {}
    form_defaults = dict(form_defaults or {})
    attachments_grouped = _group_sample_attachments(sample_payload)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if not form_defaults.get("sampling_date"):
        form_defaults["sampling_date"] = today
    if not form_defaults.get("sample_status"):
        form_defaults["sample_status"] = permit.sample.status or SAMPLE_TESTING_STATUS_DEFAULT

    sample_pdf_url = _resolve_artifact_url(
        sample_payload.get("pdf_url"),
        sample_payload.get("pdf_s3_key"),
        sample_payload.get("pdf_path"),
        sample_payload.get("pdf_relative_path"),
    )

    return templates.TemplateResponse(
        "sample_assessment.html",
        {
            "request": request,
            "user": username,
            "display_name": request.session.get("display_name") or username,
            "permit": permit,
            "form_defaults": form_defaults,
            "today": today,
            "flashes": flashes,
            "sample_status": permit.sample.status or SAMPLE_TESTING_STATUS_DEFAULT,
            "sample_notes": permit.sample.notes or "",
            "sample_summary": permit.sample.summary or {},
            "sample_pdf_url": sample_pdf_url,
            "status_options": SAMPLE_TESTING_STATUS_OPTIONS,
            "material_options": SAMPLE_TESTING_MATERIAL_OPTIONS,
            "lab_result_options": SAMPLE_TESTING_LAB_RESULT_OPTIONS,
            "entry_keys": SAMPLE_TESTING_ENTRY_KEYS,
            "determinants": SAMPLE_TESTING_DETERMINANTS,
            "attachment_categories": SAMPLE_TESTING_ATTACHMENT_CATEGORIES,
            "attachments_grouped": attachments_grouped,
        },
    )


@app.post("/permits/{permit_ref}/sample-testing", response_class=HTMLResponse)
async def sample_testing_submit(request: Request, permit_ref: str) -> Response:
    username = _require_user(request)
    scope_usernames, _ = _resolve_company_scope(username)
    record = permit_store.get_permit(username, permit_ref, allowed_usernames=scope_usernames)
    if not record:
        raise HTTPException(status_code=404, detail="Permit not found")

    form = await request.form()

    def _clean(key: str) -> str:
        return (form.get(key) or "").strip()

    def _select(key: str, options: Sequence[str], *, default: Optional[str] = None) -> str:
        value = _clean(key)
        if not value:
            return default or ""
        lowered = value.lower()
        for option in options:
            if lowered == option.lower():
                return option
        return default or ""

    status = _normalize_sample_status(_clean("sample_status"))
    notes = _clean("sample_notes") or None

    form_data: Dict[str, Any] = {
        "sampling_date": _clean("sampling_date") or datetime.utcnow().strftime("%Y-%m-%d"),
        "sampled_by_name": _clean("sampled_by_name"),
        "results_recorded_by": _clean("results_recorded_by"),
        "sample_comments": _clean("sample_comments"),
    }

    for entry_key, _label in SAMPLE_TESTING_ENTRY_KEYS:
        material = _select(f"{entry_key}_material", SAMPLE_TESTING_MATERIAL_OPTIONS)
        lab_result = _select(f"{entry_key}_lab_result", SAMPLE_TESTING_LAB_RESULT_OPTIONS)
        form_data[f"{entry_key}_number"] = _clean(f"{entry_key}_number")
        form_data[f"{entry_key}_material"] = material
        form_data[f"{entry_key}_lab_result"] = lab_result
        for det_key, _det_label in SAMPLE_TESTING_DETERMINANTS:
            present_value = _clean(f"{entry_key}_{det_key}_present")
            concentration_value = _clean(f"{entry_key}_{det_key}_concentration")
            form_data[f"{entry_key}_{det_key}_present"] = present_value
            form_data[f"{entry_key}_{det_key}_concentration"] = concentration_value

    summary = _build_sample_result_summary(form_data)
    outcome = _summarize_sample_outcome(summary)

    existing_payload = record.get("sample", {}).get("payload") if isinstance(record.get("sample"), dict) else None
    existing_attachments: List[Dict[str, Any]] = []
    if isinstance(existing_payload, dict):
        raw_attachments = existing_payload.get("attachments")
        if isinstance(raw_attachments, list):
            for item in raw_attachments:
                if isinstance(item, dict):
                    existing_attachments.append(item)

    attachments: List[Dict[str, Any]] = list(existing_attachments)
    attachment_paths = {att.get("path") for att in attachments if isinstance(att.get("path"), str)}

    if hasattr(form, "getlist"):
        for category, _label in SAMPLE_TESTING_ATTACHMENT_CATEGORIES:
            uploads = form.getlist(f"attachment_{category}")
            for upload in uploads:
                if not isinstance(upload, UploadFile) or not upload.filename:
                    continue
                try:
                    saved = await _save_sample_attachment(permit_ref, category, upload)
                except ValueError as exc:
                    _add_flash(request, str(exc), "error")
                    return RedirectResponse(url=f"/permits/{permit_ref}/sample-testing", status_code=303)
                except Exception:
                    log.exception(
                        "Failed to save sample attachment permit=%s category=%s filename=%s",
                        permit_ref,
                        category,
                        upload.filename,
                    )
                    _add_flash(request, f"Failed to save attachment '{upload.filename}'.", "error")
                    return RedirectResponse(url=f"/permits/{permit_ref}/sample-testing", status_code=303)
                if saved:
                    path_value = saved.get("path")
                    if path_value and path_value not in attachment_paths:
                        attachment_paths.add(path_value)
                        attachments.append(saved)
    else:
        log.warning("Form data missing getlist() support; skipping sample attachments for permit %s", permit_ref)

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if not attachment.get('relative_path') and attachment.get('path'):
            rel_guess = _relative_artifact_path(attachment.get('path'))
            if rel_guess:
                attachment['relative_path'] = rel_guess
        if S3_BUCKET and not attachment.get('s3_key'):
            rel = attachment.get('relative_path')
            path_value = attachment.get('path')
            try:
                if rel and path_value and Path(path_value).exists():
                    persisted_attachment = _persist_artifact(Path(rel), Path(path_value), content_type=attachment.get('content_type'))
                    if persisted_attachment.get('s3_key'):
                        attachment['s3_key'] = persisted_attachment['s3_key']
                    if persisted_attachment.get('url'):
                        attachment['url'] = persisted_attachment['url']
            except Exception:
                log.exception("Failed to sync sample attachment to S3 path=%s", attachment.get('path'))

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    pdf_path = ARTIFACTS_DIR / f"sample-testing_{permit_ref}_{timestamp}.pdf"
    sample_assets = _collect_attachment_assets(attachments)
    generate_sample_testing_pdf(
        pdf_path,
        permit_ref=permit_ref,
        form_data=form_data,
        attachments=sample_assets,
        logo_path=STATIC_DIR / 'geoprox-logo.png',
    )

    pdf_relative = pdf_path.relative_to(ARTIFACTS_DIR).as_posix()
    pdf_persisted = _persist_artifact(
        Path(pdf_relative),
        pdf_path,
        content_type="application/pdf",
        delete_local=bool(S3_BUCKET),
    )

    payload: Dict[str, Any] = {
        "form": form_data,
        "summary": summary,
        "pdf_path": str(pdf_path),
        "pdf_relative_path": pdf_relative,
        "pdf_url": pdf_persisted.get("url") or f"/artifacts/{pdf_relative}",
        "pdf_s3_key": pdf_persisted.get("s3_key"),
        "attachments": attachments,
    }

    permit_store.update_sample_assessment(
        username=username,
        permit_ref=permit_ref,
        status=status,
        outcome=outcome,
        notes=notes,
        payload=payload,
        allowed_usernames=scope_usernames,
    )
    _add_flash(request, "Sample testing record saved.", "success")
    return RedirectResponse(url=f"/permits/{permit_ref}/view", status_code=303)


@app.post("/permits/{permit_ref}/sample-status", response_class=HTMLResponse)
async def sample_status_update(request: Request, permit_ref: str) -> Response:
    username = _require_user(request)
    scope_usernames, _ = _resolve_company_scope(username)
    form = await request.form()
    status = _normalize_sample_status((form.get("sample_status") or ""))
    notes = (form.get("sample_notes") or "").strip() or None
    outcome = (form.get("sample_outcome") or "").strip() or None
    record = permit_store.update_sample_assessment(
        username=username,
        permit_ref=permit_ref,
        status=status,
        outcome=outcome,
        notes=notes,
        payload=None,
        allowed_usernames=scope_usernames,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Permit not found")
    _add_flash(request, "Sample status updated.", "success")
    return RedirectResponse(url=f"/permits/{permit_ref}/view", status_code=303)


@app.post("/api/permits/{permit_ref}/sample-testing", response_model=PermitRecordResp)
def api_update_sample_testing(request: Request, permit_ref: str, payload: PermitSampleUpdateReq) -> PermitRecordResp:
    username = _require_user(request)
    ref = (permit_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="Permit reference is required.")
    scope_usernames, _ = _resolve_company_scope(username)
    status = _normalize_sample_status(payload.status)
    notes = (payload.notes or "").strip() or None
    outcome = (payload.outcome or "").strip() or None
    payload_data = payload.payload if isinstance(payload.payload, dict) else None
    record = permit_store.update_sample_assessment(
        username=username,
        permit_ref=ref,
        status=status,
        outcome=outcome,
        notes=notes,
        payload=payload_data,
        allowed_usernames=scope_usernames,
    )
    if record:
        sample = record.get("sample") if isinstance(record, dict) else None
        if isinstance(sample, dict) and _should_generate_sample_pdf(sample):
            updated_payload = _generate_sample_pdf_payload(ref, sample)
            if updated_payload:
                refreshed = permit_store.update_sample_assessment(
                    username=username,
                    permit_ref=ref,
                    status=status,
                    outcome=outcome,
                    notes=notes,
                    payload=updated_payload,
                    allowed_usernames=scope_usernames,
                )
                if refreshed:
                    record = refreshed
    if not record:
        raise HTTPException(status_code=404, detail="Permit record not found.")
    return _permit_to_response(record)


@app.get("/app")
async def app_page(request: Request):
    _require_desktop_user(request)
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
    scope_usernames, user_map = _resolve_company_scope(user)
    raw_items = _collect_history_rows(user, scope_usernames, 200)
    annotated_rows = _annotate_history_rows(raw_items, user_map)
    items: List[Dict[str, Any]] = []
    for row in annotated_rows:
        entry = dict(row)
        entry["timestamp_display"] = _format_ddmmyy(entry.get("timestamp"), include_time=True)
        entry["pdf_path"] = _resolve_artifact_url(
            entry.get("pdf_path"),
            entry.get("pdf_s3_key"),
            entry.get("pdf_path"),
            entry.get("pdf_relative_path"),
        )
        entry["map_path"] = _resolve_artifact_url(
            entry.get("map_path"),
            entry.get("map_s3_key"),
            entry.get("map_path"),
            entry.get("map_relative_path"),
        )
        items.append(entry)
    user_type = _get_user_type(request)
    user_type_label = user_store.USER_TYPES.get(user_type, user_type.title())
    allow_desktop = user_type == "desktop"
    return templates.TemplateResponse("history.html", {
        "request": request,
        "user": user,
        "items": items,
        "is_admin": bool(request.session.get("is_admin")),
        "has_company_scope": len(scope_usernames) > 1,
        "visible_usernames": scope_usernames,
        "user_type": user_type,
        "user_type_label": user_type_label,
        "allow_desktop": allow_desktop,
    })




@app.get("/history/export")
def history_export(request: Request, limit: int = 200):
    username = _require_user(request)
    scope_usernames, user_map = _resolve_company_scope(username)
    try:
        requested_limit = int(limit or 200)
    except (TypeError, ValueError):
        requested_limit = 200
    safe_limit = max(1, min(requested_limit, 5000))
    raw_items = _collect_history_rows(username, scope_usernames, safe_limit)
    annotated_rows = _annotate_history_rows(raw_items, user_map)

    buffer = StringIO()
    fieldnames = [
        "timestamp",
        "timestamp_display",
        "location",
        "radius_m",
        "outcome",
        "permit",
        "owner_username",
        "owner_display_name",
        "pdf_url",
        "map_url",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    for row in annotated_rows:
        entry = dict(row)
        timestamp_value = entry.get("timestamp") or ""
        pdf_url = _resolve_artifact_url(
            entry.get("pdf_path"),
            entry.get("pdf_s3_key"),
            entry.get("pdf_path"),
            entry.get("pdf_relative_path"),
        )
        map_url = _resolve_artifact_url(
            entry.get("map_path"),
            entry.get("map_s3_key"),
            entry.get("map_path"),
            entry.get("map_relative_path"),
        )
        writer.writerow({
            "timestamp": timestamp_value,
            "timestamp_display": _format_ddmmyy(timestamp_value, include_time=True),
            "location": entry.get("location") or "",
            "radius_m": entry.get("radius_m") if entry.get("radius_m") is not None else "",
            "outcome": entry.get("outcome") or "",
            "permit": entry.get("permit") or "",
            "owner_username": entry.get("owner_username") or "",
            "owner_display_name": entry.get("owner_display_name") or "",
            "pdf_url": pdf_url or "",
            "map_url": map_url or "",
        })

    content = buffer.getvalue().encode("utf-8-sig")
    filename = f"search_history_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.csv"
    headers = {
        "Content-Disposition": f"attachment; filename={filename}",
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
    }
    return Response(content=content, media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/report-unidentified", response_class=HTMLResponse)
async def report_unidentified_page(request: Request) -> HTMLResponse:
    _require_user(request)
    context = {
        "request": request,
        "categories": UNIDENTIFIED_REPORT_CATEGORY_OPTIONS,
        "category_labels": UNIDENTIFIED_REPORT_CATEGORY_LABELS,
        "form": {
            "category": "",
            "name": "",
            "latitude": "",
            "longitude": "",
            "address": "",
            "notes": "",
        },
        "errors": [],
        "success": False,
    }
    return templates.TemplateResponse("report_unidentified.html", context)


@app.post("/report-unidentified", response_class=HTMLResponse)
async def report_unidentified_submit(request: Request) -> HTMLResponse:
    username = _require_user(request)
    form = await request.form()
    category = (form.get("category") or "").strip()
    name = (form.get("name") or "").strip()
    latitude_raw = (form.get("latitude") or "").strip()
    longitude_raw = (form.get("longitude") or "").strip()
    address = (form.get("address") or "").strip()
    notes = (form.get("notes") or "").strip()
    errors: List[str] = []
    valid_categories = set(UNIDENTIFIED_REPORT_CATEGORY_LABELS)
    if not category:
        errors.append("Select a category.")
    elif category not in valid_categories:
        errors.append("Select a valid category.")
    if not name:
        errors.append("Enter a name for the location.")
    if not latitude_raw or not longitude_raw:
        errors.append("Enter both latitude and longitude.")
    latitude = _parse_optional_float(latitude_raw) if latitude_raw else None
    longitude = _parse_optional_float(longitude_raw) if longitude_raw else None
    if latitude_raw and latitude is None:
        errors.append("Latitude must be a number.")
    if longitude_raw and longitude is None:
        errors.append("Longitude must be a number.")
    if not address:
        errors.append("Enter the address.")
    context_form = {
        "category": category,
        "name": name,
        "latitude": latitude_raw,
        "longitude": longitude_raw,
        "address": address,
        "notes": notes,
    }
    if errors:
        return templates.TemplateResponse("report_unidentified.html", {
            "request": request,
            "categories": UNIDENTIFIED_REPORT_CATEGORY_OPTIONS,
            "category_labels": UNIDENTIFIED_REPORT_CATEGORY_LABELS,
            "form": context_form,
            "errors": errors,
            "success": False,
        })
    record = report_store.create_report(
        category=category,
        name=name,
        latitude=latitude,
        longitude=longitude,
        address=address,
        notes=notes,
        submitted_by=username,
    )
    display_record = dict(record)
    display_record["name"] = display_record.get("name") or ""
    display_record["address"] = display_record.get("address") or ""
    display_record["notes"] = display_record.get("notes") or ""
    display_record["category_label"] = UNIDENTIFIED_REPORT_CATEGORY_LABELS.get(
        display_record.get("category"),
        str(display_record.get("category") or "").title(),
    )
    display_record["created_at_display"] = _format_ddmmyy(display_record.get("created_at"), include_time=True)
    latitude_value = display_record.get("latitude")
    longitude_value = display_record.get("longitude")
    try:
        display_record["latitude_display"] = f"{float(latitude_value):.6f}" if latitude_value is not None else ""
    except (TypeError, ValueError):
        display_record["latitude_display"] = str(latitude_value or "")
    try:
        display_record["longitude_display"] = f"{float(longitude_value):.6f}" if longitude_value is not None else ""
    except (TypeError, ValueError):
        display_record["longitude_display"] = str(longitude_value or "")
    submitted_label = user_store.get_user_by_username(username)
    if submitted_label:
        display_record["submitted_display"] = submitted_label.get("name") or submitted_label.get("username") or username
        display_record["submitted_company"] = submitted_label.get("company") or ""
    else:
        display_record["submitted_display"] = username
        display_record["submitted_company"] = ""
    return templates.TemplateResponse("report_unidentified.html", {
        "request": request,
        "categories": UNIDENTIFIED_REPORT_CATEGORY_OPTIONS,
        "category_labels": UNIDENTIFIED_REPORT_CATEGORY_LABELS,
        "form": {
            "category": "",
            "name": "",
            "latitude": "",
            "longitude": "",
            "address": "",
            "notes": "",
        },
        "errors": [],
        "success": True,
        "record": display_record,
    })


@app.get("/admin/reports/unidentified", response_class=HTMLResponse)
async def admin_unidentified_reports_page(request: Request) -> HTMLResponse:
    manager_record, is_global_admin, managed_company_id = _require_user_management_scope(request)
    if not (is_global_admin or managed_company_id):
        raise HTTPException(status_code=403, detail="Administrator access required")
    username = str(manager_record.get("username") if isinstance(manager_record, dict) else "").strip()
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    scope_usernames, user_map = _resolve_company_scope(username)
    if username not in user_map and isinstance(manager_record, dict):
        normalized_manager = dict(manager_record)
        normalized_manager["name"] = normalized_manager.get("name") or ""
        normalized_manager["company"] = normalized_manager.get("company") or ""
        user_map[username] = normalized_manager
    if is_global_admin:
        try:
            for entry in user_store.list_users(include_disabled=True):
                candidate = str(entry.get("username") or "").strip()
                if not candidate or candidate in user_map:
                    continue
                normalized = dict(entry)
                normalized["name"] = normalized.get("name") or ""
                normalized["company"] = normalized.get("company") or ""
                user_map[candidate] = normalized
        except Exception:
            log.exception("Failed to list users for unidentified reports view")
    records = report_store.list_reports()
    if not is_global_admin:
        allowed = set(scope_usernames)
        records = [record for record in records if record.get("submitted_by") in allowed]
    rows: List[Dict[str, Any]] = []
    verified_count = 0
    for record in records:
        item = dict(record)
        item["name"] = item.get("name") or ""
        item["address"] = item.get("address") or ""
        item["notes"] = item.get("notes") or ""
        item["category_label"] = UNIDENTIFIED_REPORT_CATEGORY_LABELS.get(
            item.get("category"),
            str(item.get("category") or "").title(),
        )
        item["created_at_display"] = _format_ddmmyy(item.get("created_at"), include_time=True)
        latitude_value = item.get("latitude")
        longitude_value = item.get("longitude")
        try:
            item["latitude_display"] = f"{float(latitude_value):.6f}" if latitude_value is not None else ""
        except (TypeError, ValueError):
            item["latitude_display"] = str(latitude_value or "")
        try:
            item["longitude_display"] = f"{float(longitude_value):.6f}" if longitude_value is not None else ""
        except (TypeError, ValueError):
            item["longitude_display"] = str(longitude_value or "")
        submitter = str(item.get("submitted_by") or "")
        submitter_info = user_map.get(submitter)
        if submitter_info:
            item["submitted_display"] = submitter_info.get("name") or submitter_info.get("username") or submitter
            item["submitted_company"] = submitter_info.get("company") or ""
        else:
            item["submitted_display"] = submitter or ""
            item["submitted_company"] = ""
        is_verified = bool(record.get("is_verified"))
        item["is_verified"] = is_verified
        if is_verified:
            verified_count += 1
        verified_at_value = record.get("verified_at")
        item["verified_at_display"] = _format_ddmmyy(verified_at_value, include_time=True) if verified_at_value else ""
        item["verified_by"] = record.get("verified_by") or ""
        stored_category = str(record.get("search_category") or "").strip()
        suggested_category = _default_search_category_for_report(record.get("category"))
        item["search_category"] = stored_category
        item["search_category_label"] = SEARCH_CATEGORY_LABELS.get(stored_category, "")
        item["suggested_category"] = suggested_category
        item["suggested_label"] = SEARCH_CATEGORY_LABELS.get(suggested_category, "")
        item["current_category_choice"] = stored_category or suggested_category
        item["has_coordinates"] = latitude_value is not None and longitude_value is not None
        rows.append(item)
    base_user = user_map.get(username) or (dict(manager_record) if isinstance(manager_record, dict) else {})
    company_label = base_user.get("company") or ""
    flashes = _consume_flashes(request)
    context = {
        "request": request,
        "records": rows,
        "record_count": len(rows),
        "verified_count": verified_count,
        "category_labels": UNIDENTIFIED_REPORT_CATEGORY_LABELS,
        "is_global_admin": is_global_admin,
        "current_user": username,
        "company_label": company_label,
        "flashes": flashes,
        "search_category_options": SEARCH_CATEGORY_OPTIONS,
        "search_category_labels": SEARCH_CATEGORY_LABELS,
    }
    return templates.TemplateResponse("admin_unidentified_reports.html", context)


@app.post("/admin/reports/unidentified/{report_id}/verify", response_class=HTMLResponse)
async def admin_unidentified_report_verify(request: Request, report_id: int) -> Response:
    manager_record, is_global_admin, _ = _require_user_management_scope(request)
    if not is_global_admin:
        raise HTTPException(status_code=403, detail="Global administrator access required")
    report = report_store.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    form = await request.form()
    selected_category = str(form.get("search_category") or "").strip()
    if not selected_category:
        selected_category = _default_search_category_for_report(report.get("category"))
    if selected_category not in SEARCH_CATEGORY_LABELS:
        _add_flash(request, "Select a valid search category before verifying.", "error")
        return RedirectResponse(url="/admin/reports/unidentified", status_code=303)
    if report.get("latitude") in (None, "") or report.get("longitude") in (None, ""):
        _add_flash(request, "Cannot verify a report without latitude and longitude values.", "error")
        return RedirectResponse(url="/admin/reports/unidentified", status_code=303)
    verified_by = str(manager_record.get("username") if isinstance(manager_record, dict) else "").strip()
    if not verified_by:
        raise HTTPException(status_code=401, detail="Authentication required")
    updated = report_store.verify_report(
        report_id,
        verified_by=verified_by,
        search_category=selected_category,
    )
    if not updated:
        _add_flash(request, "Unable to verify the report. Please try again.", "error")
    else:
        label = SEARCH_CATEGORY_LABELS.get(selected_category, selected_category.title())
        if updated.get("is_verified"):
            _add_flash(
                request,
                f"Report '{updated.get('name') or 'Unnamed location'}' verified and added to {label}.",
                "success",
            )
        else:
            _add_flash(request, "Report updated.", "info")
    return RedirectResponse(url="/admin/reports/unidentified", status_code=303)

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, company_id: Optional[str] = None) -> HTMLResponse:
    company_id_value = _parse_optional_int(company_id)
    _, is_global_admin, managed_company_id = _require_user_management_scope(request)
    if not is_global_admin:
        if not managed_company_id:
            raise HTTPException(status_code=403, detail="Company access required")
        company_id_value = managed_company_id
    selected_company_id = company_id_value if is_global_admin else managed_company_id
    if is_global_admin:
        companies = user_store.list_companies(include_inactive=False)
    else:
        company_record = user_store.get_company_by_id(managed_company_id) if managed_company_id else None
        companies = [company_record] if company_record else []
    users = user_store.list_users(include_disabled=True, company_id=selected_company_id)
    visible_usernames = {user["username"] for user in users}
    counts_all = history_store.get_user_search_counts()
    monthly_all = history_store.get_user_monthly_search_counts()
    search_counts = counts_all if is_global_admin else {username: counts_all.get(username, 0) for username in visible_usernames}
    monthly_counts = monthly_all if is_global_admin else {username: monthly_all.get(username, 0) for username in visible_usernames}
    flashes = _consume_flashes(request)
    managed_company = companies[0] if (not is_global_admin and companies) else None
    context = {
        "request": request,
        "users": users,
        "companies": companies,
        "selected_company": selected_company_id,
        "flashes": flashes,
        "current_user": request.session.get("user"),
        "search_counts": search_counts,
        "monthly_counts": monthly_counts,
        "license_tiers": user_store.LICENSE_TIERS,
        "user_types": user_store.USER_TYPES,
        "default_user_type": user_store.DEFAULT_USER_TYPE,
        "is_global_admin": is_global_admin,
        "managed_company": managed_company,
    }
    return templates.TemplateResponse("admin_users.html", context)

@app.get("/admin/users/export.csv")
async def admin_export_users(request: Request) -> Response:
    _, is_global_admin, managed_company_id = _require_user_management_scope(request)
    if is_global_admin:
        users = user_store.list_users(include_disabled=True)
    else:
        if not managed_company_id:
            raise HTTPException(status_code=403, detail="Company access required")
        users = user_store.list_users(include_disabled=True, company_id=managed_company_id)
    counts_all = history_store.get_user_search_counts()
    monthly_all = history_store.get_user_monthly_search_counts()
    visible_usernames = {user["username"] for user in users}
    search_counts = counts_all if is_global_admin else {username: counts_all.get(username, 0) for username in visible_usernames}
    monthly_counts = monthly_all if is_global_admin else {username: monthly_all.get(username, 0) for username in visible_usernames}
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Username",
        "Name",
        "Email",
        "Company",
        "Company Number",
        "Phone",
        "Is Admin",
        "Is Company Admin",
        "Is Active",
        "Require Password Change",
        "Total Searches",
        "Monthly Searches",
        "Monthly Limit",
        "License Tier",
        "User Type",
        "Created At",
        "Updated At",
    ])
    for user in users:
        tier_key = user.get("license_tier") or user_store.DEFAULT_LICENSE_TIER
        try:
            normalized_tier = user_store.normalize_license_tier(tier_key)
        except ValueError:
            normalized_tier = user_store.DEFAULT_LICENSE_TIER
        user_type_key = user.get("user_type") or user_store.DEFAULT_USER_TYPE
        try:
            normalized_user_type = user_store.normalize_user_type(user_type_key)
        except ValueError:
            normalized_user_type = user_store.DEFAULT_USER_TYPE
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
            int(bool(user.get("is_company_admin"))),
            int(bool(user.get("is_active"))),
            int(bool(user.get("require_password_change"))),
            int(search_counts.get(user.get("username"), 0)),
            int(monthly_counts.get(user.get("username"), 0)),
            "unlimited" if monthly_limit is None else monthly_limit,
            tier_meta.get("label", normalized_tier.title()),
            user_store.USER_TYPES.get(normalized_user_type, normalized_user_type.title()),
            user.get("created_at"),
            user.get("updated_at"),
        ])
    csv_content = buffer.getvalue()
    buffer.close()
    filename = f"geoprox-users-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return Response(csv_content, media_type='text/csv', headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.post("/admin/users/create")
async def admin_create_user(request: Request):
    manager, is_global_admin, managed_company_id = _require_user_management_scope(request)
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
    user_type_raw = (form.get("user_type") or user_store.DEFAULT_USER_TYPE).strip()
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    if not is_global_admin:
        if not managed_company_id:
            _add_flash(request, "Your account is not linked to a company.", "error")
            return _redirect_admin_users(None)
        company_id = managed_company_id
        company = manager.get("company") or ""
        is_admin = False
        is_company_admin = False
        redirect_company_id = managed_company_id
    else:
        is_admin = form.get("is_admin") == "on"
        is_company_admin = form.get("is_company_admin") == "on"
    if not username or not password or not name:
        _add_flash(request, "Username, name, and password are required.", "error")
        return _redirect_admin_users(redirect_company_id)
    try:
        license_tier = user_store.normalize_license_tier(license_tier_raw)
    except ValueError:
        _add_flash(request, "Select a valid license tier.", "error")
        return _redirect_admin_users(redirect_company_id)
    try:
        user_type = user_store.normalize_user_type(user_type_raw)
    except ValueError:
        _add_flash(request, "Select a valid user type.", "error")
        return _redirect_admin_users(redirect_company_id)
    try:
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
            is_company_admin=is_company_admin,
            license_tier=license_tier,
            user_type=user_type,
        )
        if created:
            log.info(
                "User %s created by %s (company_id=%s, is_admin=%s, is_company_admin=%s)",
                username,
                request.session.get("user"),
                created.get("company_id"),
                created.get("is_admin"),
                created.get("is_company_admin"),
            )
        _add_flash(request, f"User '{username}' created.", "success")
    except sqlite3.IntegrityError:
        _add_flash(request, "Username or email already exists.", "error")
    except ValueError as exc:
        _add_flash(request, str(exc) or "Invalid company selection.", "error")
    return _redirect_admin_users(redirect_company_id)
@app.post("/admin/users/{user_id}/update")
async def admin_update_user(request: Request, user_id: int):
    manager, is_global_admin, managed_company_id = _require_user_management_scope(request)
    form = await request.form()
    user = user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not is_global_admin:
        _ensure_user_in_scope(manager, user)
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    if not is_global_admin:
        redirect_company_id = managed_company_id
    updates: Dict[str, Any] = {}
    for field in ("name", "email", "company_number", "phone"):
        value = form.get(field)
        if value is not None:
            updates[field] = value.strip()
    if is_global_admin:
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
    user_type_choice = (form.get("user_type") or "").strip()
    if user_type_choice:
        try:
            updates["user_type"] = user_store.normalize_user_type(user_type_choice)
        except ValueError:
            _add_flash(request, "Select a valid user type.", "error")
            return _redirect_admin_users(redirect_company_id)
    if is_global_admin:
        new_is_admin = form.get("is_admin") == "on"
        updates["is_admin"] = new_is_admin
        try:
            _ensure_can_change_admin_flag(request, user, new_is_admin)
        except HTTPException as exc:
            _add_flash(request, exc.detail, "error")
            return _redirect_admin_users(redirect_company_id)
        updates["is_company_admin"] = form.get("is_company_admin") == "on"
    require_values = form.getlist("require_password_change")
    if require_values:
        updates["require_password_change"] = require_values[-1] == "on"
    if not updates:
        _add_flash(request, "Nothing to update.", "info")
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
    manager, is_global_admin, managed_company_id = _require_user_management_scope(request)
    form = await request.form()
    action = form.get("action", "disable")
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    if not is_global_admin:
        redirect_company_id = managed_company_id
    user = user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not is_global_admin:
        _ensure_user_in_scope(manager, user)
        if user.get("is_admin"):
            _add_flash(request, "Only platform administrators can change global admin accounts.", "error")
            return _redirect_admin_users(redirect_company_id)
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
    manager, is_global_admin, managed_company_id = _require_user_management_scope(request)
    form = await request.form()
    new_password = (form.get("new_password") or "").strip()
    redirect_company_id = _parse_optional_int(form.get("redirect_company_id"))
    if not is_global_admin:
        redirect_company_id = managed_company_id
    user = user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not is_global_admin:
        _ensure_user_in_scope(manager, user)
        if user.get("is_admin"):
            _add_flash(request, "Only platform administrators can reset global admin passwords.", "error")
            return _redirect_admin_users(redirect_company_id)
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
    _, is_global_admin, managed_company_id = _require_user_management_scope(request)
    effective_company_id = company_id if is_global_admin else managed_company_id
    if not is_global_admin and not managed_company_id:
        raise HTTPException(status_code=403, detail="Company access required")
    records = user_store.list_users(include_disabled=include_disabled, company_id=effective_company_id)
    counts_all = history_store.get_user_search_counts()
    monthly_all = history_store.get_user_monthly_search_counts()
    if is_global_admin:
        counts = counts_all
        monthly_counts = monthly_all
    else:
        visible_usernames = {record["username"] for record in records}
        counts = {username: counts_all.get(username, 0) for username in visible_usernames}
        monthly_counts = {username: monthly_all.get(username, 0) for username in visible_usernames}
    return [_user_to_out(record, counts, monthly_counts) for record in records]
@app.get("/api/admin/users/{user_id}", response_model=AdminUserOut)
async def api_admin_get_user(request: Request, user_id: int) -> AdminUserOut:
    manager, is_global_admin, managed_company_id = _require_user_management_scope(request)
    record = user_store.get_user_by_id(user_id)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    if not is_global_admin:
        _ensure_user_in_scope(manager, record)
    counts_all = history_store.get_user_search_counts()
    monthly_all = history_store.get_user_monthly_search_counts()
    if is_global_admin:
        counts = counts_all
        monthly_counts = {record['username']: history_store.get_monthly_search_count(record['username'])}
    else:
        counts = {record['username']: counts_all.get(record['username'], 0)}
        monthly_counts = {record['username']: monthly_all.get(record['username'], 0)}
    return _user_to_out(record, counts, monthly_counts)
@app.post("/api/admin/users", response_model=AdminUserOut, status_code=201)
async def api_admin_create_user(request: Request, payload: AdminUserCreate) -> AdminUserOut:
    manager, is_global_admin, managed_company_id = _require_user_management_scope(request)
    username = payload.username.strip()
    name = payload.name.strip()
    if not username or not name:
        raise HTTPException(status_code=400, detail="Username and name are required.")
    try:
        user_type = user_store.normalize_user_type(payload.user_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user type.")
    if not is_global_admin:
        if not managed_company_id:
            raise HTTPException(status_code=403, detail="Company access required")
        target_company_id = managed_company_id
        target_company_name = manager.get("company") or ""
        is_admin = False
        is_company_admin = False
    else:
        target_company_id = payload.company_id
        target_company_name = (payload.company or "").strip()
        is_admin = payload.is_admin
        is_company_admin = payload.is_company_admin
    try:
        record = user_store.create_user(
            username=username,
            password=payload.password,
            name=name,
            email=(payload.email or "").strip(),
            company=target_company_name,
            company_number=(payload.company_number or "").strip(),
            phone=(payload.phone or "").strip(),
            company_id=target_company_id,
            is_admin=is_admin,
            is_company_admin=is_company_admin,
            is_active=payload.is_active,
            require_password_change=payload.require_password_change,
            license_tier=payload.license_tier,
            user_type=user_type,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Username already exists.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid company selection.")
    counts_all = history_store.get_user_search_counts()
    monthly_all = history_store.get_user_monthly_search_counts()
    counts = counts_all if is_global_admin else {record['username']: counts_all.get(record['username'], 0)}
    monthly_counts = monthly_all if is_global_admin else {record['username']: monthly_all.get(record['username'], 0)}
    return _user_to_out(record, counts, monthly_counts)
@app.patch("/api/admin/users/{user_id}", response_model=AdminUserOut)
async def api_admin_update_user(request: Request, user_id: int, payload: AdminUserUpdate) -> AdminUserOut:
    manager, is_global_admin, managed_company_id = _require_user_management_scope(request)
    record = user_store.get_user_by_id(user_id)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    if not is_global_admin:
        _ensure_user_in_scope(manager, record)
    data = payload.model_dump(exclude_unset=True)
    if not is_global_admin:
        for key in ("company", "company_id", "is_admin", "is_company_admin"):
            data.pop(key, None)
    updates: Dict[str, Any] = {}
    for field in ("name", "email", "company_number", "phone"):
        if field in data and data[field] is not None:
            updates[field] = data[field].strip()
    if is_global_admin and "company" in data:
        updates["company"] = (data["company"] or "").strip()
    if is_global_admin and "company_id" in data:
        updates["company_id"] = data["company_id"]
        if data["company_id"] is None and "company" not in updates:
            updates["company"] = ""
    if "license_tier" in data and data["license_tier"] is not None:
        updates["license_tier"] = data["license_tier"]
    if "user_type" in data:
        try:
            updates["user_type"] = user_store.normalize_user_type(data["user_type"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user type.")
    if is_global_admin and "is_admin" in data:
        _ensure_can_change_admin_flag(request, record, data["is_admin"])
        updates["is_admin"] = data["is_admin"]
    if is_global_admin and "is_company_admin" in data and data["is_company_admin"] is not None:
        updates["is_company_admin"] = data["is_company_admin"]
    if "require_password_change" in data:
        updates["require_password_change"] = data["require_password_change"]
    target_is_admin = updates.get("is_admin", record["is_admin"])
    if "is_active" in data:
        if not is_global_admin and record.get("is_admin") and not data["is_active"]:
            raise HTTPException(status_code=403, detail="Only platform administrators can disable global admin accounts.")
        _ensure_can_change_active_status(
            request,
            record,
            enable=data["is_active"],
            target_is_admin=target_is_admin,
        )
        updates["is_active"] = data["is_active"]
    if not updates:
        counts_all = history_store.get_user_search_counts()
        monthly_all = history_store.get_user_monthly_search_counts()
        counts = counts_all if is_global_admin else {record['username']: counts_all.get(record['username'], 0)}
        monthly_counts = monthly_all if is_global_admin else {record['username']: monthly_all.get(record['username'], 0)}
        return _user_to_out(record, counts, monthly_counts)
    try:
        user_store.update_user(record["id"], **updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid company selection.")
    updated = user_store.get_user_by_id(record["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    counts_all = history_store.get_user_search_counts()
    monthly_all = history_store.get_user_monthly_search_counts()
    counts = counts_all if is_global_admin else {updated['username']: counts_all.get(updated['username'], 0)}
    monthly_counts = monthly_all if is_global_admin else {updated['username']: monthly_all.get(updated['username'], 0)}
    return _user_to_out(updated, counts, monthly_counts)
@app.post("/api/admin/users/{user_id}/reset-password", response_model=AdminActionResult)
async def api_admin_reset_password(request: Request, user_id: int, payload: AdminPasswordReset) -> AdminActionResult:
    manager, is_global_admin, managed_company_id = _require_user_management_scope(request)
    new_password = payload.new_password.strip()
    if not new_password:
        raise HTTPException(status_code=400, detail="Password cannot be empty.")
    user = user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not is_global_admin:
        _ensure_user_in_scope(manager, user)
        if user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Only platform administrators can reset global admin passwords.")
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



@app.get("/api/permits/search", response_model=List[PermitSearchItem])
def api_search_permits(request: Request, query: str = "", limit: int = 20):
    username = _require_user(request)
    scope_usernames, user_map = _resolve_company_scope(username)
    permit_records = _collect_permit_records(username, query, limit, scope_usernames)
    annotated = _enrich_permit_items(permit_records, user_map)
    field_names = PermitSearchItem.model_fields.keys()
    return [
        PermitSearchItem(**{field: entry.get(field) for field in field_names})
        for entry in annotated
    ]


@app.get("/api/permits/export")
def api_export_permits(request: Request, query: str = "", limit: int = 500):
    username = _require_user(request)
    scope_usernames, user_map = _resolve_company_scope(username)
    try:
        safe_limit = int(limit or 500)
    except (TypeError, ValueError):
        safe_limit = 500
    safe_limit = max(1, min(safe_limit, 2000))
    permit_records = _collect_permit_records(username, query, safe_limit, scope_usernames)
    annotated_items = _enrich_permit_items(permit_records, user_map)

    EMPTY_TOKEN = "__EMPTY__"
    filter_fields = [
        "permit_ref",
        "owner_username",
        "desktop_status",
        "desktop_outcome",
        "site_status",
        "site_bituminous",
        "site_sub_base",
        "desktop_date",
        "site_date",
    ]
    column_map = {
        "permit_ref": "Permit",
        "owner_username": "Created By",
        "desktop_status": "Desktop Status",
        "desktop_outcome": "Desktop Outcome",
        "site_status": "Field Status",
        "site_bituminous": "Bituminous Outcome",
        "site_sub_base": "Sub-base Outcome",
        "desktop_date": "Desktop Date",
        "site_date": "Site Date",
    }

    active_filters: Dict[str, Set[str]] = {}
    for field in filter_fields:
        values = request.query_params.getlist(f"filter_{field}")
        if values:
            active_filters[field] = set(values)

    columns = [
        "Permit",
        "Created By",
        "Desktop Status",
        "Desktop Outcome",
        "Field Status",
        "Bituminous Outcome",
        "Sub-base Outcome",
        "Desktop Date",
        "Site Date",
    ]

    def _format_date(primary: Any, fallback: Any = None) -> str:
        candidate = primary or fallback
        if not candidate:
            return ""
        if isinstance(candidate, datetime):
            dt = candidate
        else:
            text = str(candidate).strip()
            if not text:
                return ""
            try:
                iso_text = text
                if iso_text.endswith("Z"):
                    iso_text = iso_text[:-1] + "+00:00"
                dt = datetime.fromisoformat(iso_text)
            except ValueError:
                return text
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.strftime("%Y-%m-%d %H:%M")

    def _normalise_filter_value(value: Any) -> str:
        if value is None:
            return EMPTY_TOKEN
        text = str(value).strip()
        return EMPTY_TOKEN if not text else text

    rows: List[Dict[str, Any]] = []
    for item in annotated_items:
        bituminous_value = item.get("site_bituminous") or item.get("site_outcome") or ""
        sub_base_value = item.get("site_sub_base") or item.get("site_outcome") or ""
        desktop_date_value = _format_date(item.get("desktop_date"), item.get("created_at"))
        site_date_value = _format_date(item.get("site_date"), item.get("updated_at"))
        rows.append(
            {
                "Permit": item.get("permit_ref") or "",
                "Created By": item.get("owner_username") or "",
                "Desktop Status": item.get("desktop_status") or "",
                "Desktop Outcome": item.get("desktop_outcome") or "",
                "Field Status": item.get("site_status") or "",
                "Bituminous Outcome": bituminous_value,
                "Sub-base Outcome": sub_base_value,
                "Desktop Date": desktop_date_value,
                "Site Date": site_date_value,
            }
        )

    if active_filters:
        filtered_rows: List[Dict[str, Any]] = []
        for row in rows:
            matches = True
            for field, selected in active_filters.items():
                column_name = column_map.get(field)
                if not column_name:
                    continue
                value_key = _normalise_filter_value(row.get(column_name))
                if selected and value_key not in selected:
                    matches = False
                    break
            if matches:
                filtered_rows.append(row)
        rows = filtered_rows

    if rows:
        df = pd.DataFrame(rows, columns=columns)
    else:
        df = pd.DataFrame(columns=columns)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    filename = f"permit_export_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.xlsx"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@app.post("/api/permits", response_model=PermitRecordResp)
def api_save_permit_record(request: Request, payload: PermitSaveReq):
    username = _require_desktop_user(request)
    permit_ref = (payload.permit_ref or "").strip()
    if not permit_ref:
        raise HTTPException(status_code=400, detail="Permit reference is required.")
    result_payload = payload.result or {}
    if isinstance(result_payload, dict):
        _persist_search_artifacts(result_payload)
        artifacts = result_payload.get("artifacts")
        if isinstance(artifacts, dict):
            result_payload["artifacts"] = _normalize_search_artifacts(artifacts)
    record = permit_store.save_permit(
        username=username,
        permit_ref=permit_ref,
        search_result=result_payload,
    )
    if not record:
        raise HTTPException(status_code=500, detail="Unable to save permit record.")
    return _permit_to_response(record)


@app.get("/api/permits/{permit_ref}", response_model=PermitRecordResp)
def api_get_permit_record(request: Request, permit_ref: str, owner: Optional[str] = None):
    username = _require_user(request)
    ref = (permit_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="Permit reference is required.")
    scope_usernames, user_map = _resolve_company_scope(username)
    owner_param = owner.strip() if owner else None
    if owner_param == "":
        owner_param = None
    record = _get_permit_record(username, ref, owner_param, scope_usernames)
    if not record:
        raise HTTPException(status_code=404, detail="Permit record not found.")
    owner_username = record.get("username")
    owner_display = None
    if owner_username:
        owner_record = user_map.get(owner_username)
        if owner_record and owner_record.get("name"):
            owner_display = owner_record.get("name")
        else:
            owner_display = owner_username
    return _permit_to_response(record, owner_display_name=owner_display)


@app.post("/api/permits/{permit_ref}/site-assessment", response_model=PermitRecordResp)
def api_update_site_assessment(request: Request, permit_ref: str, payload: PermitSiteUpdateReq):
    username = _require_user(request)
    ref = (permit_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="Permit reference is required.")
    scope_usernames, _ = _resolve_company_scope(username)
    status = _normalize_site_status(payload.status)
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
        allowed_usernames=scope_usernames,
    )
    if record:
        site = record.get("site") if isinstance(record, dict) else None
        if isinstance(site, dict) and _should_generate_site_pdf(site):
            updated_payload = _generate_site_pdf_payload(ref, site)
            if updated_payload:
                refreshed = permit_store.update_site_assessment(
                    username=username,
                    permit_ref=ref,
                    status=status,
                    outcome=outcome,
                    notes=notes,
                    payload=updated_payload,
                    allowed_usernames=scope_usernames,
                )
                if refreshed:
                    record = refreshed
    if not record:
        raise HTTPException(status_code=404, detail="Permit record not found.")
    return _permit_to_response(record)

@app.post("/api/search", response_model=SearchResp)
def api_search(request: Request, req: SearchReq):
    username = _require_desktop_user(request)
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

        extra_locations: List[Dict[str, Any]] = []
        for verified in report_store.list_verified_reports():
            lat_raw = verified.get("latitude")
            lon_raw = verified.get("longitude")
            try:
                lat_val = float(lat_raw)
                lon_val = float(lon_raw)
            except (TypeError, ValueError):
                continue
            category_key = str(verified.get("search_category") or "").strip()
            if not category_key:
                category_key = _default_search_category_for_report(verified.get("category"))
            if category_key not in SEARCH_CATEGORY_LABELS:
                continue
            extra_locations.append(
                {
                    "id": verified.get("id"),
                    "name": verified.get("name"),
                    "lat": lat_val,
                    "lon": lon_val,
                    "address": verified.get("address"),
                    "notes": verified.get("notes"),
                    "category": category_key,
                    "submitted_by": verified.get("submitted_by"),
                }
            )

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
            extra_locations=extra_locations,
        )

        log.info(f"Search result: {result}")

        if not result:
            raise RuntimeError("run_geoprox_search returned None")

        _persist_search_artifacts(result)
        arts = result.get("artifacts", {}) or {}
        normalized_artifacts = _normalize_search_artifacts(arts)
        result["artifacts"] = normalized_artifacts

        selection_info = result.get("selection") or {}
        if "mode" not in selection_info:
            selection_info["mode"] = selection_mode
        if polygon_vertices and not selection_info.get("polygon"):
            selection_info["polygon"] = [[float(lat), float(lon)] for lat, lon in polygon_vertices]
        result["selection"] = selection_info

        timestamp = datetime.utcnow().isoformat() + "Z"
        outcome = result.get("summary", {}).get("outcome")
        pdf_link = normalized_artifacts.get("pdf_url") or normalized_artifacts.get("pdf_download_url")
        map_link = normalized_artifacts.get("map_url") or normalized_artifacts.get("map_embed_url")

        history_store.record_search(
            username=username,
            timestamp=timestamp,
            location=safe_location,
            radius_m=req.radius_m,
            outcome=outcome,
            permit=req.permit,
            pdf_path=pdf_link,
            map_path=map_link,
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

def _persist_search_artifacts(payload: Dict[str, Any]) -> None:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return
    if not S3_BUCKET:
        return

    updated = dict(artifacts)
    if updated.get("pdf_s3_key") or updated.get("pdf_key"):
        for _, field in [
            ("pdf", "pdf_path"),
            ("map_html", "map_html_path"),
            ("map", "map_path"),
            ("map_image", "map_image_path"),
        ]:
            raw_path = updated.get(field)
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = (ARTIFACTS_DIR / raw_path).resolve()
            if candidate.exists():
                try:
                    candidate.unlink()
                except Exception:
                    log.debug("Unable to remove cached artifact %s", candidate)
        return

    changed = False

    field_defs = [
        ("pdf", "pdf_path"),
        ("map_html", "map_html_path"),
        ("map", "map_path"),
        ("map_image", "map_image_path"),
    ]

    for base, field in field_defs:
        raw_path = updated.get(field)
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (ARTIFACTS_DIR / raw_path).resolve()
        if not candidate.exists():
            continue
        relative = _relative_artifact_path(str(candidate))
        if not relative:
            try:
                relative = candidate.relative_to(ARTIFACTS_DIR).as_posix()
            except Exception:
                relative = candidate.name
        content_type = mimetypes.guess_type(candidate.name)[0]
        persisted = _persist_artifact(
            Path(relative),
            candidate,
            content_type=content_type,
            delete_local=True,
        )
        updated[f"{base}_relative_path"] = relative
        if persisted.get("s3_key"):
            updated[f"{base}_s3_key"] = persisted["s3_key"]
        if persisted.get("url"):
            updated[f"{base}_url"] = persisted["url"]
        changed = True

    if changed:
        payload["artifacts"] = updated

