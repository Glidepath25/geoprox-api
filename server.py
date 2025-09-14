# server.py  (repo root)
import os, sys
# Ensure our code and vendored deps are first on the path
sys.path[:0] = ["/app", "/app/.python_packages"]

from geoprox.main import app  # <- imports your FastAPI app
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
