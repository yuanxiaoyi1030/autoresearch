# Purpose: Starts the v0.2 loopback API only from the required Conda d2l environment.
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn

from research_runtime.config import Settings


def main() -> None:
    if os.environ.get("CONDA_DEFAULT_ENV") != "d2l":
        raise SystemExit("API must run after conda activate d2l")
    settings = Settings.from_env()
    uvicorn.run("apps.backend.main:create_app", factory=True, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
