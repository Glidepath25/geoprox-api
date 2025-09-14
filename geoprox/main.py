from fastapi import FastAPI
import logging

app = FastAPI(title="GeoProx API")

logger = logging.getLogger("uvicorn.error")

@app.on_event("startup")
async def _log_startup():
    paths = [r.path for r in app.routes]
    logger.info("GeoProx main module file: %s", __file__)
    logger.info("GeoProx routes at startup: %s", paths)

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/healthz")
def healthz():
    return {"ok": True}
