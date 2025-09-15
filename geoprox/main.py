# geoprox/main.py
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from geoprox.core import run_geoprox_search

def _normalise_location(s: str) -> str:
    """
    Accepts:
      - 'lat,lon' with optional spaces, e.g. '54.35, -6.65'
      - what3words starting with '///'
    Returns a canonical 'lat,lon' or the original what3words string.
    Raises HTTPException(400) on invalid input.
    """
    if not s:
        raise HTTPException(status_code=400, detail="Location is required.")

    s = s.strip()
    if s.startswith("///"):
        return s  # let the core handle what3words

    # Try 'lat,lon' with loose spacing
    try:
        parts = s.replace(" ", "").split(",")
        if len(parts) != 2:
            raise ValueError("Expected two comma-separated numbers.")
        lat = float(parts[0])
        lon = float(parts[1])
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ValueError("Latitude/longitude out of range.")
        # Canonical string—no spaces
        return f"{lat},{lon}"
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid location. Use 'lat,lon' (e.g. '54.35,-6.65') or a '///what.three.words' address.",
        )

# -----------------------------------------------------------------------------
# Setup & paths
# -----------------------------------------------------------------------------
log = logging.getLogger("uvicorn.error")

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[1]

STATIC_DIR = (REPO_ROOT / "static").resolve()
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "artifacts")).resolve()
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# FastAPI app  (ONLY ONE app instance!)
# -----------------------------------------------------------------------------
app = FastAPI(title="GeoProx API", version="1.0.0")

# CORS (relaxed; tighten for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static assets at /static
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    log.info(f"Static mounted: {STATIC_DIR}")
else:
    log.warning(f"static/ not found at {STATIC_DIR}")

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class SearchReq(BaseModel):
    location: str = Field(..., description="lat,lon or ///what.three.words")
    radius_m: int = Field(..., ge=10, le=20000)
    categories: List[str] = Field(default_factory=list)
    permit: Optional[str] = None
    max_results: Optional[int] = Field(default=None, ge=1, le=10000)

class SearchResp(BaseModel):
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    debug: Optional[Dict[str, Any]] = None

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/healthz")
def healthz() -> Dict[str, bool]:
    return {"ok": True}

# Serve index.html for both / and /index.html
@app.get("/", response_class=FileResponse)
@app.get("/index.html", response_class=FileResponse)
def landing():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        # fallback so deploy health checks still succeed
        return JSONResponse({"status": "ok"})
    return FileResponse(str(index_file), media_type="text/html")

# Serve generated artifacts (PDF, HTML, and _files/*)
@app.get("/artifacts/{path:path}")
def get_artifact(path: str):
    """
    Serve generated artifacts and their sidecar assets (e.g. *_files/*).
    """
    full = (ARTIFACTS_DIR / path).resolve()
    if not str(full).startswith(str(ARTIFACTS_DIR)):
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not full.exists():
        raise HTTPException(status_code=404, detail="Not Found")

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
def api_search(req: SearchReq):
    try:
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)

        # NEW: normalise location to avoid None being unpacked in the core
        safe_location = _normalise_location(req.location)

        result = run_geoprox_search(
            location=safe_location,
            radius_m=req.radius_m,
            categories=req.categories or [],  # protect None
            permit=req.permit or "",
            out_dir=ARTIFACTS_DIR,
            w3w_key=os.environ.get("OXT6XQ19")
            max_results=req.max_results,
        )

        # Defensive: If the core ever returns None, surface a friendly error
        if result is None:
            raise HTTPException(status_code=500, detail="Search returned no result.")

        arts = result.get("artifacts", {}) or {}
        if arts.get("pdf_path") and not arts.get("pdf_url"):
            arts["pdf_url"] = f"/artifacts/{Path(arts['pdf_path']).name}"
        if arts.get("map_html_path") and not arts.get("map_url"):
            arts["map_url"] = f"/artifacts/{Path(arts['map_html_path']).name}"
        result["artifacts"] = arts

        return SearchResp(status="done", result=result)

    except HTTPException:
        # re-raise validation errors cleanly to the client
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=8)
        log.error(f"GeoProx failure: {e}\n{tb}")
        return SearchResp(status="error", error=str(e), debug={"trace": tb})

