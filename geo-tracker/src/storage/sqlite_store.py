"""
SQLite storage. Three tables:
  - runs:     one row per (prompt x model x timestamp) execution
  - mentions: one row per entity per run (whether mentioned or not)
  - citations: one row per cited URL in a response (Perplexity gives these natively)

Keep the schema flat and obvious. We'll add views for reporting, not new tables.
"""
import sqlite3
import json
from pathlib import Path
from src.models import ModelResponse, Mention


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_id TEXT NOT NULL,
    response_text TEXT,
    timestamp TEXT NOT NULL,
    latency_ms INTEGER,
    error TEXT,
    raw_payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_client_time ON runs(client_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_runs_prompt_model ON runs(prompt_id, model_name);

CREATE TABLE IF NOT EXISTS mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id INTEGER NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    is_mentioned INTEGER NOT NULL,
    position INTEGER,
    sentiment TEXT,
    context_snippet TEXT,
    cited_url TEXT,
    judge_confidence REAL,
    FOREIGN KEY (response_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_name, is_mentioned);
CREATE INDEX IF NOT EXISTS idx_mentions_response ON mentions(response_id);

CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    FOREIGN KEY (response_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_citations_url ON citations(url);
"""


class SQLiteStore:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def save_response(self, response: ModelResponse) -> int:
        """Insert a ModelResponse and any associated citations.
        Returns the new run row's ID for use as a FK in mentions."""
        cur = self.conn.execute(
            """
            INSERT INTO runs
            (client_id, prompt_id, prompt_text, model_name, model_id,
             response_text, timestamp, latency_ms, error, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                response.client_id,
                response.prompt_id,
                response.prompt_text,
                response.model_name,
                response.model_id,
                response.response_text,
                response.timestamp,
                response.latency_ms,
                response.error,
                json.dumps(response.raw_payload) if response.raw_payload else None,
            ),
        )
        run_id = cur.lastrowid

        # Insert citations
        for citation in response.citations:
            self.conn.execute(
                "INSERT INTO citations (response_id, url, title, snippet) VALUES (?, ?, ?, ?)",
                (run_id, citation.url, citation.title, citation.snippet),
            )

        self.conn.commit()
        return run_id

    def save_mentions(self, mentions: list[Mention]) -> None:
        for m in mentions:
            self.conn.execute(
                """
                INSERT INTO mentions
                (response_id, entity_name, entity_type, is_mentioned,
                 position, sentiment, context_snippet, cited_url, judge_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    m.response_id,
                    m.entity_name,
                    m.entity_type,
                    int(m.is_mentioned),
                    m.position,
                    m.sentiment,
                    m.context_snippet,
                    m.cited_url,
                    m.judge_confidence,
                ),
            )
        self.conn.commit()

    def summary_by_entity(self, client_id: str) -> list[dict]:
        """Return mention counts grouped by entity and model for one client."""
        rows = self.conn.execute(
            """
            SELECT
                m.entity_name,
                m.entity_type,
                r.model_name,
                COUNT(*) AS total_prompts,
                SUM(m.is_mentioned) AS mention_count,
                ROUND(AVG(CASE WHEN m.is_mentioned THEN m.position END), 2) AS avg_position
            FROM mentions m
            JOIN runs r ON r.id = m.response_id
            WHERE r.client_id = ?
            GROUP BY m.entity_name, r.model_name
            ORDER BY mention_count DESC
            """,
            (client_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()
