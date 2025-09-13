# app/main.py
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path
import traceback, os

from .core import run_geoprox_search

from fastapi.responses import FileResponse
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

@app.get("/")
def root():
    return FileResponse(str(ROOT / "client.html"))


ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "artifacts"))

# >>> Hardcoded w3w key (replace with yours)
WHAT3WORDS_API_KEY = os.environ.get("WHAT3WORDS_API_KEY", "OXT6XQ19")

# <<<

app = FastAPI(title="GeoProx API (MVP)", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchReq(BaseModel):
    location: str = Field("", examples=["54.5973,-5.9301", "///filled.count.soap"])
    radius_m: int = Field(ge=10, le=3000, default=2000)
    categories: list[str] = Field(
        default_factory=lambda: [
            "manufacturing","petrol_stations","substations","sewage_treatment",
            "landfills","scrapyards","waste_disposal","gas_holding","mines"
        ]
    )
    permit: str = Field(default="K6001-DAF-ACON-95test")

class SearchResp(BaseModel):
    status: str
    result: dict | None = None
    error: str | None = None

@app.get("/ping")
def ping():
    return {"msg": "pong"}

@app.post("/search", response_model=SearchResp)
def search(req: SearchReq, bg: BackgroundTasks):
    try:
        result = run_geoprox_search(
            location=req.location,
            radius_m=req.radius_m,
            categories=req.categories,
            permit=req.permit,
            out_dir=ARTIFACTS_DIR,
            w3w_key=WHAT3WORDS_API_KEY,  # <- always provided
        )
        return {"status": "done", "result": result}
    except ValueError as e:
        return {"status": "error", "result": None, "error": str(e)}
    except Exception as e:
        tb = traceback.format_exc(limit=8)
        return {"status": "error", "result": None, "error": f"{e}\n{tb}"}


app = FastAPI(title="GeoProx API (MVP)", version="0.1.0")

# CORS so client.html can call the API from http://127.0.0.1:5500
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # ok for MVP; tighten in prod
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchReq(BaseModel):
    location: str = Field("", examples=["54.5973,-5.9301", "///filled.count.soap"])
    radius_m: int = Field(ge=10, le=3000, default=2000)
    categories: list[str] = Field(
        default_factory=lambda: [
            "manufacturing","petrol_stations","substations","sewage_treatment",
            "landfills","scrapyards","waste_disposal","gas_holding","mines"
        ]
    )
    permit: str = Field(default="K6001-DAF-ACON-95841")

class SearchResp(BaseModel):
    status: str
    result: dict | None = None
    error: str | None = None

@app.get("/ping")
def ping():
    return {"msg": "pong"}

@app.post("/search", response_model=SearchResp)
def search(req: SearchReq, bg: BackgroundTasks):
    try:
        result = run_geoprox_search(
            location=req.location,
            radius_m=req.radius_m,
            categories=req.categories,
            permit=req.permit,
            out_dir=ARTIFACTS_DIR,
            w3w_key=WHAT3WORDS_API_KEY,
        )
        return {"status": "done", "result": result}
    except ValueError as e:
        return {"status": "error", "result": None, "error": str(e)}
    except Exception as e:
        tb = traceback.format_exc(limit=8)
        return {"status": "error", "result": None, "error": f"{e}\n{tb}"}
