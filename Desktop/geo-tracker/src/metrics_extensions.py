"""
Extended analytics functions for the dashboard.
These complement compute_metrics (which returns the hero strip) with the
per-prompt and per-model breakdowns the dashboard shows below the fold.

Pure SQL on the existing schema -- no new tables, no Streamlit dependency.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional


def _connect(db_path: str) -> Optional[sqlite3.Connection]:
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def models_used(client_id: str, db_path: str = "data/geo_tracker.db") -> list[str]:
    """Distinct models with at least one successful response for this client.
    Used to conditionally render the by-model section (skip if only 1 model)."""
    conn = _connect(db_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """SELECT DISTINCT model_name FROM runs
               WHERE client_id = ? AND error IS NULL""",
            (client_id,),
        ).fetchall()
        return [r["model_name"] for r in rows]
    finally:
        conn.close()


def by_prompt(
    client_id: str,
    business_aliases: list[str],
    db_path: str = "data/geo_tracker.db",
) -> list[dict]:
    """For each prompt: how many responses ran, whether the business appeared,
    and the top businesses surfaced. One row per prompt_id.

    business_aliases: normalized names that count as 'the user' (for the
    'you appeared in X of Y responses for this prompt' metric).
    """
    conn = _connect(db_path)
    if conn is None:
        return []
    try:
        # Get all prompts run for this client
        prompts = conn.execute(
            """SELECT DISTINCT prompt_id, prompt_text FROM runs
               WHERE client_id = ? AND error IS NULL
               ORDER BY prompt_id""",
            (client_id,),
        ).fetchall()

        results = []
        for p in prompts:
            prompt_id = p["prompt_id"]

            # Total responses for this prompt
            total = conn.execute(
                """SELECT COUNT(*) FROM runs
                   WHERE client_id = ? AND prompt_id = ? AND error IS NULL""",
                (client_id, prompt_id),
            ).fetchone()[0]

            # User business mentions for this prompt
            placeholders = ",".join("?" for _ in business_aliases) or "''"
            user_appearances = conn.execute(
                f"""SELECT COUNT(DISTINCT eb.response_id), AVG(eb.position)
                    FROM extracted_businesses eb
                    JOIN runs r ON r.id = eb.response_id
                    WHERE r.client_id = ? AND r.prompt_id = ?
                      AND r.error IS NULL
                      AND eb.normalized_name IN ({placeholders})""",
                (client_id, prompt_id, *business_aliases),
            ).fetchone() if business_aliases else (0, None)

            user_count = user_appearances[0] or 0
            user_avg_pos = user_appearances[1]

            # Top 5 businesses surfaced for this prompt (excluding user)
            top_others = conn.execute(
                f"""SELECT eb.normalized_name,
                           MAX(eb.name) AS display_name,
                           COUNT(*) AS n,
                           ROUND(AVG(eb.position), 1) AS avg_pos
                    FROM extracted_businesses eb
                    JOIN runs r ON r.id = eb.response_id
                    WHERE r.client_id = ? AND r.prompt_id = ?
                      AND r.error IS NULL
                      AND eb.normalized_name NOT IN ({placeholders})
                    GROUP BY eb.normalized_name
                    HAVING n >= 2
                    ORDER BY n DESC, avg_pos ASC
                    LIMIT 5""",
                (client_id, prompt_id, *business_aliases),
            ).fetchall()

            results.append({
                "prompt_id": prompt_id,
                "prompt_text": p["prompt_text"],
                "total_responses": total,
                "user_appearances": user_count,
                "user_appearance_rate": (user_count / total) if total else 0.0,
                "user_avg_position": round(user_avg_pos, 1) if user_avg_pos else None,
                "top_others": [dict(r) for r in top_others],
            })
        return results
    finally:
        conn.close()


def by_model(
    client_id: str,
    business_aliases: list[str],
    db_path: str = "data/geo_tracker.db",
) -> list[dict]:
    """One row per model. Shows how the user fares across each tracked model.
    Dashboard renders this only when len(models_used) >= 2."""
    conn = _connect(db_path)
    if conn is None:
        return []
    try:
        models = models_used(client_id, db_path)
        results = []
        placeholders = ",".join("?" for _ in business_aliases) or "''"

        for model in models:
            total = conn.execute(
                """SELECT COUNT(*) FROM runs
                   WHERE client_id = ? AND model_name = ? AND error IS NULL""",
                (client_id, model),
            ).fetchone()[0]

            if business_aliases:
                row = conn.execute(
                    f"""SELECT COUNT(DISTINCT eb.response_id), AVG(eb.position)
                        FROM extracted_businesses eb
                        JOIN runs r ON r.id = eb.response_id
                        WHERE r.client_id = ? AND r.model_name = ?
                          AND r.error IS NULL
                          AND eb.normalized_name IN ({placeholders})""",
                    (client_id, model, *business_aliases),
                ).fetchone()
                user_count = row[0] or 0
                user_avg_pos = row[1]
            else:
                user_count = 0
                user_avg_pos = None

            results.append({
                "model_name": model,
                "total_responses": total,
                "user_appearances": user_count,
                "user_appearance_rate": (user_count / total) if total else 0.0,
                "user_avg_position": round(user_avg_pos, 1) if user_avg_pos else None,
            })
        return results
    finally:
        conn.close()


def full_leaderboard(
    client_id: str,
    db_path: str = "data/geo_tracker.db",
    min_mentions: int = 2,
    limit: int = 25,
) -> list[dict]:
    """Full ranked leaderboard for the dashboard table view.
    Same shape as the runner's summary, but exposed as a clean function."""
    conn = _connect(db_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT
                eb.normalized_name,
                MAX(eb.name) AS display_name,
                COUNT(*) AS total_mentions,
                COUNT(DISTINCT eb.response_id) AS unique_responses,
                COUNT(DISTINCT r.prompt_id) AS unique_prompts,
                COUNT(DISTINCT r.model_name) AS models_mentioning,
                ROUND(AVG(eb.position), 2) AS avg_position,
                SUM(CASE WHEN eb.position = 1 THEN 1 ELSE 0 END) AS times_ranked_first,
                SUM(CASE WHEN eb.sentiment = 'positive' THEN 1 ELSE 0 END) AS positive_mentions
            FROM extracted_businesses eb
            JOIN runs r ON r.id = eb.response_id
            WHERE r.client_id = ? AND r.error IS NULL
            GROUP BY eb.normalized_name
            HAVING total_mentions >= ?
            ORDER BY total_mentions DESC, avg_position ASC
            LIMIT ?
            """,
            (client_id, min_mentions, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()