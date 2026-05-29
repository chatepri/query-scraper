"""
Hero metrics for the v1 dashboard.

Three numbers shown side-by-side as a metric strip when a customer's
results come back from a run:

  1. Mention rate    -- % of all model responses that mention the business
  2. Top-3 rate      -- % of mentions placed in position 1-3 (quality)
  3. Rank vs peers   -- "You're #N of M businesses surfaced in your category"

All three derive from the existing extracted_businesses table.
"""
from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Kept in sync with src/parsers/llm_judge.py normalize_fallback().
# If they drift, business matching will silently fail.
_PARENS = re.compile(r"\s*\([^)]*\)\s*")
_DASH_TRAIL = re.compile(r"\s*[\u2013\u2014-]\s+.+$")
_SUFFIX = re.compile(
    r"\b(inc|llc|corp|co|ltd|l\.?p\.?a\.?|p\.?c\.?|company)\.?$", re.I
)
_TRAILERS = re.compile(
    r"\s+(training center|training|workforce development|school of management|"
    r"usa|center|group|firm|bootcamp)\b.*$", re.I)
_LEADING_THE = re.compile(r"^the\s+", re.I)
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Collapse a business name to its canonical matching key."""
    n = _PARENS.sub(" ", name)
    n = _DASH_TRAIL.sub("", n)
    n = _LEADING_THE.sub("", n)
    n = _SUFFIX.sub("", n)
    n = _TRAILERS.sub("", n)
    n = n.lower().strip(" ,.-")
    n = _SPACES.sub(" ", n)
    return n


@dataclass
class HeroMetrics:
    """The three numbers plus raw counts that back them.

    Field-ordering rule: every field WITHOUT a default comes first.
    """
    business_name: str

    mention_rate: float          # 0.0 -- 1.0
    mentions_count: int          # responses where business appeared
    total_responses: int         # all successful responses

    top3_rate: Optional[float]   # None when total_user_mentions == 0
    top3_count: int
    total_user_mentions: int     # all mentions w/ a position assigned

    rank: Optional[int]          # 1-indexed; None if business not found
    total_competitors: int       # distinct normalized_names in leaderboard
    total_entities_surfaced: int

    matched_normalized_names: list[str] = field(default_factory=list)

    def as_strip(self) -> dict:
        """Friendly dict for the dashboard metric strip."""
        return {
            "mention_rate_pct": round(self.mention_rate * 100, 1),
            "mention_rate_caption": (
                f"{self.mentions_count} of {self.total_responses} responses"
            ),
            "top3_rate_pct": (
                round(self.top3_rate * 100, 1) if self.top3_rate is not None else None
            ),
            "top3_rate_caption": (
                f"{self.top3_count} of {self.total_user_mentions} mentions"
                if self.total_user_mentions else "no mentions yet"
            ),
            "rank": self.rank,
            "total_competitors": self.total_competitors,
            "rank_caption": (
                f"#{self.rank} of {self.total_competitors}"
                if self.rank else f"not ranked ({self.total_competitors} competitors)"
            ),
            "surfaced_caption": (
                f"{self.total_entities_surfaced} total entities surfaced"
            ),
        }


def compute_metrics(
    client_id: str,
    business_name: str,
    db_path: str = "data/geo_tracker.db",
    extra_aliases: Optional[list[str]] = None,
    min_mentions_for_competitor: int = 2,
) -> HeroMetrics:
    """Compute the three hero metrics for the dashboard strip.

    Args:
        client_id: filter to runs from this client only
        business_name: canonical name; normalized to find matching extractions
        db_path: SQLite path
        extra_aliases: additional normalized names to match (covers judge drift)

    Returns:
        HeroMetrics with all three numbers + raw counts.
        Returns zero-state metrics if the database doesn't exist yet.
    """
    if not Path(db_path).exists():
        return _zero_state(business_name)

    primary = normalize_name(business_name)
    aliases = {primary}
    if extra_aliases:
        aliases.update(normalize_name(a) for a in extra_aliases)
    aliases.discard("")
    aliases_list = sorted(aliases)
    placeholders = ",".join("?" for _ in aliases_list)

    conn = sqlite3.connect(db_path)
    try:
        total_responses = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE client_id = ? AND error IS NULL",
            (client_id,),
        ).fetchone()[0]

        if total_responses == 0:
            return _zero_state(business_name)

        mentions_count = conn.execute(
            f"""
            SELECT COUNT(DISTINCT eb.response_id)
            FROM extracted_businesses eb
            JOIN runs r ON r.id = eb.response_id
            WHERE r.client_id = ?
              AND r.error IS NULL
              AND eb.normalized_name IN ({placeholders})
            """,
            (client_id, *aliases_list),
        ).fetchone()[0]
        mention_rate = mentions_count / total_responses

        positions = conn.execute(
            f"""
            SELECT eb.position
            FROM extracted_businesses eb
            JOIN runs r ON r.id = eb.response_id
            WHERE r.client_id = ?
              AND r.error IS NULL
              AND eb.normalized_name IN ({placeholders})
              AND eb.position IS NOT NULL
            """,
            (client_id, *aliases_list),
        ).fetchall()
        total_user_mentions = len(positions)
        top3_count = sum(1 for (p,) in positions if p <= 3)
        top3_rate = (top3_count / total_user_mentions) if total_user_mentions else None

        leaderboard = conn.execute(
            """
            SELECT eb.normalized_name, COUNT(*) AS n
            FROM extracted_businesses eb
            JOIN runs r ON r.id = eb.response_id
            WHERE r.client_id = ? AND r.error IS NULL
            GROUP BY eb.normalized_name
            HAVING n >= ?
            ORDER BY n DESC, eb.normalized_name ASC
            """,
            (client_id, min_mentions_for_competitor),
        ).fetchall()

        total_entities_surfaced = conn.execute(
            """
            SELECT COUNT(DISTINCT eb.normalized_name)
            FROM extracted_businesses eb
            JOIN runs r ON r.id = eb.response_id
            WHERE r.client_id = ? AND r.error IS NULL
            """,
            (client_id,),
        ).fetchone()[0]

        total_competitors = len(leaderboard)
        rank = None
        matched_names: list[str] = []
        for i, (norm_name, _) in enumerate(leaderboard, 1):
            if norm_name in aliases:
                if rank is None:
                    rank = i
                matched_names.append(norm_name)

        return HeroMetrics(
            business_name=business_name,
            mention_rate=mention_rate,
            mentions_count=mentions_count,
            total_responses=total_responses,
            top3_rate=top3_rate,
            top3_count=top3_count,
            total_user_mentions=total_user_mentions,
            rank=rank,
            total_competitors=total_competitors,
            total_entities_surfaced=total_entities_surfaced,
            matched_normalized_names=matched_names,
        )
    finally:
        conn.close()


def _zero_state(business_name: str) -> HeroMetrics:
    return HeroMetrics(
        business_name=business_name,
        mention_rate=0.0,
        mentions_count=0,
        total_responses=0,
        top3_rate=None,
        top3_count=0,
        total_user_mentions=0,
        rank=None,
        total_entities_surfaced=0,
        total_competitors=0,
    )