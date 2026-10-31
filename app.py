"""
Pterodactyl / Jexactyl entrypoint.

Startup command ends with:
  /usr/local/bin/python /home/container/app.py

Pip installs go to .local (egg --prefix .local); we add that to sys.path here.
"""

from __future__ import annotations

import os
import site
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _bootstrap_paths() -> None:
    # Egg: pip install -U --prefix .local -r requirements.txt
    for sp in sorted(ROOT.glob(".local/lib/python*/site-packages")):
        site.addsitedir(str(sp))
    # Ensure package dir is importable when cwd differs
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


_bootstrap_paths()


def main() -> None:
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT") or os.environ.get("PORT") or "8080")
    print("Omnix Link: Server marked as starting...", flush=True)
    # Reload off in production egg
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
