import os, sys, uvicorn

# Make sure our code is importable regardless of where App Runner mounts the repo
for p in ["/code", "/workspace", "/app", "/app/.python_packages"]:
    if p not in sys.path:
        sys.path.insert(0, p)

from geoprox.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
