from pathlib import Path

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Timeouts for Overpass calls
HTTP_TIMEOUT_SEC = 25.0

# Default what3words key; you can hard-code or use an env var override
W3W_KEY_DEFAULT = "OXT6XQ19"  # <- replace if needed
