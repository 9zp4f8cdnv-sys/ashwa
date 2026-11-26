"""The company's records: a local SQLite file (company.db by default).

Everything the CEO agent knows about the company between sessions lives here:
the founder's profile, the AI staff and their KPIs, tasks, approvals, ethics
checks, the money ledger and the decision log.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS founder_profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY,
    role TEXT NOT NULL,
    mission TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    retired_reason TEXT,
    replaces_id INTEGER REFERENCES staff(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS staff_changes (
    id INTEGER PRIMARY KEY,
    staff_id INTEGER NOT NULL REFERENCES staff(id),
    change TEXT NOT NULL,          -- hired | rewritten | retired
    version INTEGER NOT NULL,
    reason TEXT NOT NULL,
    system_prompt TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kpis (
    id INTEGER PRIMARY KEY,
    staff_id INTEGER NOT NULL REFERENCES staff(id),
    name TEXT NOT NULL,
    target REAL NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'higher' CHECK (direction IN ('higher', 'lower')),
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS kpi_readings (
    id INTEGER PRIMARY KEY,
    kpi_id INTEGER NOT NULL REFERENCES kpis(id),
    value REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    staff_id INTEGER NOT NULL REFERENCES staff(id),
    staff_version INTEGER NOT NULL,
    task TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('done', 'failed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ethics_checks (
    id INTEGER PRIMARY KEY,
    item TEXT NOT NULL,
    results TEXT NOT NULL,         -- JSON list of {area, rating, note}
    passed INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    amount_cents INTEGER,
    ethics_check_id INTEGER REFERENCES ethics_checks(id),
    status TEXT NOT NULL CHECK (status IN ('approved', 'denied')),
    founder_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    description TEXT NOT NULL,
    approval_id INTEGER REFERENCES approvals(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    if path is None:
        from .paths import DB_FILE
        path = DB_FILE
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
