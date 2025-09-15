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

log = logging.getLogger("uvicorn.error")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[1]
STATIC_DIR = (REPO_ROOT / "static").resolve()
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "artifacts")).resolve()
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="GeoProx API", version="0.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# only mount /static (not as root) for assets like logo/index
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    log.info(f"Static dir: {STATIC_DIR}")
else:
    log.warning(f"static/ not found at {STATIC_DIR}")

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
# Helpers
# ---------------------------------------------------------------------------
def _normalise_location(s: str) -> str:
    """
    Accept:
      - 'lat,lon' (spaces allowed) e.g. '54.35, -6.65'
      - what3words starting with '///'
    Return canonical 'lat,lon' or the what3words string.
    Raise HTTP 400 on invalid input.
    """
    if not s:
        raise HTTPException(status_code=400, detail="Location is required.")
    s = s.strip()
    if s.startswith("///"):
        return s

    # Try parse "lat,lon"
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
            detail="Invalid location. Use 'lat,lon' (e.g. '54.35,-6.65') "
                   "or a '///what.three.words' address.",
        )


def _safe_artifact(path: str) -> Path:
    """Join safely within ARTIFACTS_DIR and ensure it exists."""
    full = (ARTIFACTS_DIR / path).resolve()
    if not str(full).startswith(str(ARTIFACTS_DIR)):
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not full.exists():
        raise HTTPException(status_code=404, detail="Not Found")
    return full


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz() -> Dict[str, bool]:
    return {"ok": True}


@app.get("/", response_class=FileResponse)
@app.get("/index.html", response_class=FileResponse)
def homepage():
    """Serve SPA landing page from /static/index.html."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        # keep health happy while deploys/renames happen
        return JSONResponse({"status": "ok"})
    return FileResponse(str(index_file), media_type="text/html")


@app.get("/artifacts/{path:path}")
def get_artifact(path: str):
    """
    Serve generated artifacts and their nested asset files (e.g. leaflet _files).
    """
    full = _safe_artifact(path)
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
    """
    Run a GeoProx search and return summary + artifact URLs.
    """
    try:
        safe_location = _normalise_location(req.location)

        result = run_geoprox_search(
            location=safe_location,
            radius_m=req.radius_m,
            categories=req.categories or [],
            permit=req.permit or "",
            out_dir=ARTIFACTS_DIR,
            w3w_key=os.environ.get("WHAT3WORDS_API_KEY"),
            max_results=req.max_results,
        )

        if result is None:
            raise HTTPException(status_code=500, detail="Search returned no result")

        arts = result.get("artifacts", {}) or {}
        # generate local URLs if only paths are present
        if arts.get("pdf_path") and not arts.get("pdf_url"):
            arts["pdf_url"] = f"/artifacts/{Path(arts['pdf_path']).name}"
        if arts.get("map_html_path") and not arts.get("map_url"):
            arts["map_url"] = f"/artifacts/{Path(arts['map_html_path']).name}"
        result["artifacts"] = arts

        return SearchResp(status="done", result=result)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=8)
        log.error(f"GeoProx failure: {e}\n{tb}")
        return SearchResp(status="error", error=str(e), debug={"trace": tb})
