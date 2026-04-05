"""
Server entry point for GST Compliance OpenEnv.

Forwards to env.main (FastAPI on port 7860).
This file satisfies multi-mode deployment checks.
"""
import sys
import os

# Ensure project root is on the path when run from server/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from env.main import app  # noqa: F401  — re-exported for uvicorn discovery


def main(host: str = "0.0.0.0", port: int = 7860) -> None:
    """Start the GST Compliance OpenEnv server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
