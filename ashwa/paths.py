"""Where Ashwa keeps its files. Everything lives under ASHWA_DATA_DIR
(default: the current folder), so a cloud host can put it on a persistent disk."""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("ASHWA_DATA_DIR", "."))
STATE_FILE = DATA_DIR / ".ashwa.json"
DB_FILE = Path(os.environ.get("ASHWA_DB") or DATA_DIR / "company.db")
REPORTS_DIR = DATA_DIR / "reports"
OUTPUTS_DIR = DATA_DIR / "outputs"
