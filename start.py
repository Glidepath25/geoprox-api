# start.py (repo root)
import os, sys, pprint, uvicorn

# Prepend all likely source roots so imports work regardless of where App Runner mounts the repo
CANDIDATES = ["/code", "/workspace", "/app"]
for p in CANDIDATES + ["/app/.python_packages"]:
    if p not in sys.path:
        sys.path.insert(0, p)

print("=== DEBUG ===")
print("CWD:", os.getcwd())
print("CANDIDATES EXISTS:", {p: os.path.isdir(p) for p in CANDIDATES})
print("SYSPATH_HEAD:", sys.path[:8])

# Try to locate the package
found = None
for p in CANDIDATES:
    gp = os.path.join(p, "geoprox")
    if os.path.isdir(gp):
        found = gp
        break
print("GEOPROX_DIR:", found or "NOT FOUND")

from geoprox.main import app  # will raise if path is still wrong

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
