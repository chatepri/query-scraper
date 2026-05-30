"""
Single source of truth for "what client profiles exist."

The sidebar selector, dashboard, and CLI all use this so the answer
to 'what clients are there' is computed the same way everywhere.
"""
from pathlib import Path
from typing import Optional
import yaml


CLIENTS_DIR = Path("config/clients")
DRAFTS_DIR = CLIENTS_DIR / "auto"


def list_clients(include_drafts: bool = False) -> list[dict]:
    """Return all client profiles, sorted by client name.

    Each entry: {id, name, path, is_draft}. Drafts (in auto/) are excluded
    by default since they shouldn't appear in the sidebar as active profiles.
    """
    if not CLIENTS_DIR.exists():
        return []

    results = []
    for yaml_path in CLIENTS_DIR.glob("*.yaml"):
        results.append(_load_client_meta(yaml_path, is_draft=False))

    if include_drafts and DRAFTS_DIR.exists():
        for yaml_path in DRAFTS_DIR.glob("*.yaml"):
            results.append(_load_client_meta(yaml_path, is_draft=True))

    return [r for r in results if r is not None]


def get_client(client_id: str) -> Optional[dict]:
    """Look up a client by ID. Searches non-draft profiles first."""
    for c in list_clients(include_drafts=True):
        if c["id"] == client_id:
            return c
    return None


def _load_client_meta(yaml_path: Path, is_draft: bool) -> Optional[dict]:
    """Read just the client.id and client.name from a YAML, no prompts."""
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
        client = data.get("client", {})
        return {
            "id": client.get("id") or yaml_path.stem,
            "name": client.get("name") or yaml_path.stem,
            "path": str(yaml_path),
            "is_draft": is_draft,
        }
    except Exception:
        return None

def erase_all_client_data(client_id: str) -> dict:
    """GDPR-style purge: removes the profile YAML, all SQLite records, and
    subprocess logs for this client_id. Irreversible.

    Returns a dict with what was deleted and any errors encountered.

    This is the right-to-erasure operation. When a customer requests data
    deletion under GDPR Article 17 or CCPA equivalents, this is what fulfills
    the request. Audit log for compliance is the caller's responsibility.
    """
    import sqlite3
    from pathlib import Path

    deleted_yamls = []
    deleted_logs = []
    sqlite_deleted = {}
    errors = []

    # 1. Delete profile YAML(s) — both the durable and any drafts
    for c in list_clients(include_drafts=True):
        if c["id"] == client_id:
            try:
                Path(c["path"]).unlink()
                deleted_yamls.append(c["path"])
            except Exception as e:
                errors.append(f"YAML {c['path']}: {e}")

    # 2. Delete all SQLite records for this client_id
    db_path = "data/geo_tracker.db"
    if Path(db_path).exists():
        try:
            conn = sqlite3.connect(db_path, timeout=10)
            # Order matters: extracted_businesses and citations FK back to runs
            cur = conn.execute(
                """DELETE FROM extracted_businesses
                   WHERE response_id IN (
                       SELECT id FROM runs WHERE client_id = ?
                   )""", (client_id,))
            sqlite_deleted["extracted_businesses"] = cur.rowcount

            cur = conn.execute(
                """DELETE FROM citations
                   WHERE response_id IN (
                       SELECT id FROM runs WHERE client_id = ?
                   )""", (client_id,))
            sqlite_deleted["citations"] = cur.rowcount

            cur = conn.execute(
                "DELETE FROM runs WHERE client_id = ?", (client_id,))
            sqlite_deleted["runs"] = cur.rowcount

            cur = conn.execute(
                "DELETE FROM run_status WHERE client_id = ?", (client_id,))
            sqlite_deleted["run_status"] = cur.rowcount

            conn.commit()
            conn.close()
        except Exception as e:
            errors.append(f"SQLite: {e}")

    # 3. Delete subprocess logs
    log_dir = Path("data/subprocess_logs")
    if log_dir.exists():
        for log_file in log_dir.glob(f"{client_id}*.log"):
            try:
                log_file.unlink()
                deleted_logs.append(str(log_file))
            except Exception as e:
                errors.append(f"Log {log_file}: {e}")

    return {
        "deleted_yamls": deleted_yamls,
        "deleted_logs": deleted_logs,
        "sqlite_records_deleted": sqlite_deleted,
        "errors": errors,
        "summary": (
            f"{len(deleted_yamls)} YAML(s), "
            f"{sqlite_deleted.get('runs', 0)} runs, "
            f"{sqlite_deleted.get('extracted_businesses', 0)} extractions, "
            f"{sqlite_deleted.get('citations', 0)} citations, "
            f"{sqlite_deleted.get('run_status', 0)} status records, "
            f"{len(deleted_logs)} log file(s)"
        ),
    }

def delete_client(client_id: str, include_drafts: bool = True) -> dict:
    """Remove a client's profile YAML(s) from disk.

    Returns a dict reporting what was deleted:
      {deleted: [path, ...], not_found: bool, errors: [str, ...]}

    Does NOT delete the client's run data from SQLite — historical metrics
    are preserved. To wipe data too, the caller can issue a separate
    DELETE on the runs/extracted_businesses tables.
    """
    from pathlib import Path

    deleted = []
    errors = []

    for c in list_clients(include_drafts=include_drafts):
        if c["id"] == client_id:
            try:
                Path(c["path"]).unlink()
                deleted.append(c["path"])
            except Exception as e:
                errors.append(f"{c['path']}: {e}")

    return {
        "deleted": deleted,
        "not_found": len(deleted) == 0 and len(errors) == 0,
        "errors": errors,
    }