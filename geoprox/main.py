# geoprox/main.py
from __future__ import annotations

import os
import logging
import traceback
from typing import List, Optional, Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from geoprox.core import run_geoprox_search

import os
from fastapi.responses import FileResponse
from fastapi import HTTPException

# Where your API already writes artifacts:
ARTIFACTS_DIR = os.environ.get("ARTIFACTS_DIR", "/tmp/artifacts")

def _safe_join_artifact(name: str) -> str:
    # prevent directory traversal
    name = os.path.basename(name)
    full = os.path.join(ARTIFACTS_DIR, name)
    if not os.path.abspath(full).startswith(os.path.abspath(ARTIFACTS_DIR)):
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not os.path.exists(full):
        raise HTTPException(status_code=404, detail="File not found")
    return full

@app.get("/artifacts/pdf/{name}")
def get_pdf_artifact(name: str):
    full = _safe_join_artifact(name)
    return FileResponse(full, media_type="application/pdf", filename=name)

@app.get("/artifacts/html/{name}")
def get_html_artifact(name: str):
    full = _safe_join_artifact(name)
    return FileResponse(full, media_type="text/html; charset=utf-8", filename=name)


# ---------- App & CORS ----------
app = FastAPI(title="GeoProx API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for prod
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

log = logging.getLogger("uvicorn.error")

# ---------- Models ----------
class SearchReq(BaseModel):
    location: str = Field(..., examples=["54.5973,-5.9301", "///filled.count.soap"])
    radius_m: int = Field(..., ge=10, le=20000, examples=[2000])
    # Use your actual category keys (from core OSM_FILTERS): e.g. manufacturing, petrol_stations, etc.
    categories: List[str] = Field(default_factory=list, examples=[["manufacturing", "petrol_stations"]])
    permit: Optional[str] = Field(default=None, description="Permit/reference string used in output filenames")
    max_results: Optional[int] = Field(default=500, ge=1, le=10000)

class SearchResp(BaseModel):
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    debug: Optional[Dict[str, Any]] = None

# ---------- Basic routes ----------
@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import Request

app.mount("/static", StaticFiles(directory="geoprox/static"), name="static")
templates = Jinja2Templates(directory="geoprox/templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ---------- GeoProx endpoints ----------
@app.post("/api/search", response_model=SearchResp)
def api_search(req: SearchReq):
    """
    Runs the GeoProx search and returns results (JSON + artifact paths/URLs).
    """
    try:
        out_dir = os.environ.get("ARTIFACTS_DIR", "/tmp/artifacts")
        os.makedirs(out_dir, exist_ok=True)

        w3w_key = os.environ.get("WHAT3WORDS_API_KEY")  # optional

        result = run_geoprox_search(
            location=req.location,
            radius_m=req.radius_m,
            categories=req.categories,
            permit=req.permit,
            out_dir=out_dir,
            w3w_key=w3w_key,
            max_results=req.max_results or 500,
        )
        return SearchResp(status="done", result=result)

    except ValueError as e:
        log.warning(f"GeoProx user error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        tb = traceback.format_exc(limit=8)
        log.error(f"GeoProx failure: {e}\n{tb}")
        return SearchResp(status="error", error=str(e), debug={"trace": tb})

# (Optional) stub for a future report endpoint
class ReportReq(BaseModel):
    job_id: Optional[str] = None
    items: Optional[List[Dict[str, Any]]] = None
    title: Optional[str] = "GeoProx Report"

@app.post("/api/report", response_model=SearchResp)
def api_report(req: ReportReq):
    try:
        # hook up if you add a dedicated report builder
        return SearchResp(status="done", result={"report_path": None})
    except Exception as e:
        tb = traceback.format_exc(limit=8)
        log.error(f"Report failure: {e}\n{tb}")
        return SearchResp(status="error", error=str(e), debug={"trace": tb})
