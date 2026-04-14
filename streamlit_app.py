from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from job_tracker.ui.streamlit_app import run_app
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "Could not import 'job_tracker'. Ensure the 'job_tracker/' folder is committed "
        "to the repo root alongside 'streamlit_app.py'."
    ) from exc

if __name__ == "__main__":
    run_app()

