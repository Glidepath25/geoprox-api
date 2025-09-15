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
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# geoprox/main.py

from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
# ... your other imports ...

app = FastAPI(title="GeoProx API")

# CORS (leave as you already have it)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)

# ---- Static paths ----
# repo root = parent of geoprox/
REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = (REPO_ROOT / "static").resolve()

# serve /static/* (logo, css, js, etc.)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    print("WARNING: static/ directory not found")

# ---- Landing page routes ----
@app.get("/", response_class=FileResponse)
def root():
    """
    Serve the SPA landing page from static/index.html
    """
    index_html = STATIC_DIR / "index.html"
    if not index_html.exists():
        # fallback, useful for health probes during deploys
        return JSONResponse({"status": "ok"})
    return FileResponse(str(index_html))

@app.get("/index.html", response_class=FileResponse)
def index_html():
    """
    Support direct /index.html links (browsers, bookmarks, etc.)
    """
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(str(index_file))

# ... keep the remainder of your API (healthz, /api/search, /artifacts/*, etc.) ...

log = logging.getLogger("uvicorn.error")

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[1]
STATIC_DIR = (REPO_ROOT / "static").resolve()

app = FastAPI(title="GeoProx API")

# Mount only /static for assets (logo, etc.)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    log.info(f"STATIC_DIR resolved to: {STATIC_DIR} (exists={STATIC_DIR.exists()})")
else:
    log.warning(f"STATIC_DIR not found: {STATIC_DIR}")

# Serve index.html for both / and /index.html
@app.get("/", response_class=FileResponse)
@app.get("/index.html", response_class=FileResponse)
def homepage():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        log.error(f"index.html not found at {index_file}")
        return JSONResponse({"status": "ok"})  # fallback so healthz still passes
    return FileResponse(str(index_file), media_type="text/html")


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[1]

STATIC_DIR = (REPO_ROOT / "static").resolve()
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "artifacts")).resolve()
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="GeoProx API", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets (logo, index.html, etc.)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    log.info(f"Static dir mounted: {STATIC_DIR}")
else:
    log.warning("⚠️ static/ directory not found")

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/artifacts/{path:path}")
def get_artifact(path: str):
    """Serve generated artifacts and nested _files assets"""
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
    """Run GeoProx search and return results"""
    try:
        w3w_key = os.environ.get("WHAT3WORDS_API_KEY")

        result = run_geoprox_search(
            location=req.location,
            radius_m=req.radius_m,
            categories=req.categories,
            permit=req.permit or "",
            out_dir=ARTIFACTS_DIR,
            w3w_key=w3w_key,
            max_results=req.max_results,
        )

        arts = result.get("artifacts", {}) or {}
        if arts.get("pdf_path") and not arts.get("pdf_url"):
            arts["pdf_url"] = f"/artifacts/{Path(arts['pdf_path']).name}"
        if arts.get("map_html_path") and not arts.get("map_url"):
            arts["map_url"] = f"/artifacts/{Path(arts['map_html_path']).name}"

        result["artifacts"] = arts
        return SearchResp(status="done", result=result)

    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=6)
        log.error(f"GeoProx error: {e}\n{tb}")
        return SearchResp(status="error", error=str(e), debug={"trace": tb})
