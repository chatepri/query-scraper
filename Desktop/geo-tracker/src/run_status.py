"""
Run status tracking — stored in SQLite for clean migration to multi-user.

One row per client_id. State transitions:

    (no row) -> running -> completed
                       |-> failed
                       |-> orphaned  (subprocess died without updating)

Orphan detection runs on every get_status() call:
  - If state='running' but PID doesn't exist anymore, we flip to 'orphaned'
    and the dashboard surfaces a "run died unexpectedly" message.

This module owns the table schema and all writes/reads against it.
Other modules (runner, dashboard) call these functions; never write directly.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil


SCHEMA = """
CREATE TABLE IF NOT EXISTS run_status (
    client_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    pid INTEGER,
    mode TEXT,
    total_calls INTEGER,
    completed_calls INTEGER DEFAULT 0,
    current_prompt_id TEXT,
    error_message TEXT
);
"""


def _now() -> str:
    return datetime.utcnow().isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def start_run(client_id, mode, total_calls, pid=None, db_path="data/geo_tracker.db"):
    pid = pid or os.getpid()
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO run_status
              (client_id, state, started_at, updated_at, pid, mode,
               total_calls, completed_calls, current_prompt_id, error_message,
               finished_at)
            VALUES (?, 'running', ?, ?, ?, ?, ?, 0, NULL, NULL, NULL)
            ON CONFLICT(client_id) DO UPDATE SET
              state='running',
              started_at=excluded.started_at,
              updated_at=excluded.updated_at,
              pid=excluded.pid,
              mode=excluded.mode,
              total_calls=excluded.total_calls,
              completed_calls=0,
              current_prompt_id=NULL,
              error_message=NULL,
              finished_at=NULL
            """,
            (client_id, _now(), _now(), pid, mode, total_calls),
        )
        conn.commit()
    finally:
        conn.close()


def update_progress(client_id, completed_calls, current_prompt_id=None,
                    db_path="data/geo_tracker.db"):
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE run_status SET completed_calls=?, current_prompt_id=?,
                                     updated_at=?
               WHERE client_id=?""",
            (completed_calls, current_prompt_id, _now(), client_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_completed(client_id, db_path="data/geo_tracker.db"):
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE run_status SET state='completed', finished_at=?,
                                     updated_at=?, current_prompt_id=NULL
               WHERE client_id=?""",
            (_now(), _now(), client_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_failed(client_id, error_message, db_path="data/geo_tracker.db"):
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE run_status SET state='failed', error_message=?,
                                     finished_at=?, updated_at=?
               WHERE client_id=?""",
            (error_message[:500], _now(), _now(), client_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_status(client_id, db_path="data/geo_tracker.db"):
    if not Path(db_path).exists():
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM run_status WHERE client_id=?", (client_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["state"] == "running" and d["pid"]:
            if not psutil.pid_exists(d["pid"]):
                conn.execute(
                    """UPDATE run_status SET state='orphaned',
                       error_message='Subprocess died without updating status.',
                       finished_at=?, updated_at=? WHERE client_id=?""",
                    (_now(), _now(), client_id),
                )
                conn.commit()
                d["state"] = "orphaned"
                d["error_message"] = "Subprocess died without updating status."
        if d.get("total_calls"):
            d["percent"] = round(100 * (d["completed_calls"] or 0) / d["total_calls"], 1)
        else:
            d["percent"] = 0.0
        return d
    finally:
        conn.close()


def list_active(db_path="data/geo_tracker.db"):
    if not Path(db_path).exists():
        return []
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM run_status WHERE state='running' ORDER BY started_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()