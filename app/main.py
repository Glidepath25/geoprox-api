# app/main.py
from fastapi import FastAPI

app = FastAPI(title="GeoProx API (minimal)")

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/healthz")
def healthz():
    return {"ok": True}
