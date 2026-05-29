"""
SQLite storage. Three tables:
  - runs:                 one row per (prompt x model x iteration x timestamp)
  - extracted_businesses: one row per business found in each response
  - citations:            one row per cited URL in a response
"""
import sqlite3
import json
from pathlib import Path
from src.models import ModelResponse, ExtractedBusiness


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_id TEXT NOT NULL,
    run_iteration INTEGER NOT NULL DEFAULT 1,
    response_text TEXT,
    timestamp TEXT NOT NULL,
    latency_ms INTEGER,
    grounding_mode TEXT,
    error TEXT,
    raw_payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_client_time ON runs(client_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_runs_prompt_model ON runs(prompt_id, model_name);
CREATE INDEX IF NOT EXISTS idx_runs_iteration ON runs(prompt_id, model_name, run_iteration);

CREATE TABLE IF NOT EXISTS extracted_businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    entity_type TEXT,
    position INTEGER,
    sentiment TEXT,
    context_snippet TEXT,
    confidence REAL,
    FOREIGN KEY (response_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_extracted_normalized ON extracted_businesses(normalized_name);
CREATE INDEX IF NOT EXISTS idx_extracted_response ON extracted_businesses(response_id);

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
        cur = self.conn.execute(
            """
            INSERT INTO runs
            (client_id, prompt_id, prompt_text, model_name, model_id,
             run_iteration, response_text, timestamp, latency_ms,
             grounding_mode, error, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                response.client_id, response.prompt_id, response.prompt_text,
                response.model_name, response.model_id, response.run_iteration,
                response.response_text, response.timestamp, response.latency_ms,
                response.grounding_mode, response.error,
                json.dumps(response.raw_payload) if response.raw_payload else None,
            ),
        )
        run_id = cur.lastrowid

        for citation in response.citations:
            self.conn.execute(
                "INSERT INTO citations (response_id, url, title, snippet) VALUES (?, ?, ?, ?)",
                (run_id, citation.url, citation.title, citation.snippet),
            )

        self.conn.commit()
        return run_id

    def save_extractions(self, businesses: list[ExtractedBusiness]) -> None:
        for b in businesses:
            self.conn.execute(
                """
                INSERT INTO extracted_businesses
                (response_id, name, normalized_name, entity_type,
                 position, sentiment, context_snippet, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    b.response_id, b.name, b.normalized_name, b.entity_type,
                    b.position, b.sentiment, b.context_snippet, b.confidence,
                ),
            )
        self.conn.commit()

    def leaderboard(self, client_id: str, limit: int = 25) -> list[dict]:
        """Top businesses by total mentions across all models, prompts, iterations."""
        rows = self.conn.execute(
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
            WHERE r.client_id = ?
            GROUP BY eb.normalized_name
            ORDER BY total_mentions DESC, avg_position ASC
            LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()