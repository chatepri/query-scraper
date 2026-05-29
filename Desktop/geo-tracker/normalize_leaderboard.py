"""
Post-processing normalizer for the existing extracted_businesses data.

Reads the SQLite DB, applies aggressive normalization rules to collapse
variant business names, filters out non-service-provider entities
(buildings, government initiatives, etc.), and prints a cleaned leaderboard.

This does NOT modify the database. It's a view over existing data so we can
see the real ranking without re-running 150 API calls.

Usage:
  python normalize_leaderboard.py
  python normalize_leaderboard.py --limit 30
  python normalize_leaderboard.py --show-noise   # also print what was filtered
  python normalize_leaderboard.py --client yten  # filter to one client
"""
import argparse
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = "data/geo_tracker.db"


# Patterns to strip from names during normalization
PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*")
EM_DASH_TRAIL = re.compile(r"\s*[–—-]\s*.+$")
CORP_SUFFIXES = re.compile(
    r"\b(inc|llc|corp|co|ltd|l\.?p\.?a\.?|p\.?c\.?|lp|llp|company)\.?$",
    re.IGNORECASE,
)
DESCRIPTIVE_TRAILS = re.compile(
    r"\s+(training center|training|workforce development( office)?|"
    r"school of management|usa|buffalo|cleveland|"
    r"office|offices|center|consortium|group|firm|"
    r"professional and executive development|ped)\b.*$",
    re.IGNORECASE,
)
LEADING_THE = re.compile(r"^the\s+", re.IGNORECASE)
MULTIPLE_SPACES = re.compile(r"\s+")


# Names matching these patterns are NOT service providers; exclude them
NOISE_PATTERNS = [
    re.compile(r"\bregus\b", re.IGNORECASE),               # office building
    re.compile(r"^empire ai", re.IGNORECASE),              # NYS funding initiative
    re.compile(r"\bm&t bank\b", re.IGNORECASE),            # sponsor/client, not vendor
    re.compile(r"\bmeetup\b", re.IGNORECASE),              # community event
    re.compile(r"\bai in western new york\b", re.IGNORECASE),  # meetup name
    re.compile(r"^\s*$"),                                  # empty
]


def aggressive_normalize(name: str) -> str:
    """Collapse a business name to its canonical form for grouping.

    The goal is to make these all collapse to "logical operations":
      - "Logical Operations"
      - "Logical Operations Training Center"
      - "Logical Operations Training"
      - "Logical Operations, LLC"
    """
    n = name.strip()
    n = PARENTHETICAL.sub(" ", n)         # remove "(YTEN)", "(UB)", etc.
    n = EM_DASH_TRAIL.sub("", n)          # remove "Logical Operations – Training"
    n = LEADING_THE.sub("", n)            # remove leading "The "
    n = CORP_SUFFIXES.sub("", n)          # remove ", LLC", " Inc", etc.
    n = DESCRIPTIVE_TRAILS.sub("", n)     # remove " Training Center", " USA", etc.
    n = n.lower().strip(" ,.-")
    n = MULTIPLE_SPACES.sub(" ", n)
    return n


def is_noise(name: str) -> bool:
    """True if this name should be excluded from the leaderboard."""
    return any(p.search(name) for p in NOISE_PATTERNS)


def load_data(client_id: str = None) -> list[dict]:
    """Pull every extracted_business row with its associated run info."""
    if not Path(DB_PATH).exists():
        raise FileNotFoundError(f"No database at {DB_PATH}. Run python run.py first.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    where = "WHERE r.client_id = ?" if client_id else ""
    params = (client_id,) if client_id else ()

    rows = conn.execute(
        f"""
        SELECT
            eb.name,
            eb.normalized_name AS judge_normalized,
            eb.entity_type,
            eb.position,
            eb.sentiment,
            eb.confidence,
            r.id AS response_id,
            r.prompt_id,
            r.model_name,
            r.run_iteration,
            r.client_id
        FROM extracted_businesses eb
        JOIN runs r ON r.id = eb.response_id
        {where}
        """,
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_leaderboard(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Apply normalization + filtering. Returns (clean_leaderboard, noise_rows)."""
    groups = defaultdict(lambda: {
        "display_names": set(),
        "entity_types": set(),
        "positions": [],
        "sentiments": [],
        "response_ids": set(),
        "prompt_ids": set(),
        "model_names": set(),
        "total_mentions": 0,
        "first_place_count": 0,
        "positive_count": 0,
    })
    noise = []

    for row in rows:
        name = row["name"]
        if is_noise(name):
            noise.append(row)
            continue

        key = aggressive_normalize(name)
        if not key:
            noise.append(row)
            continue

        g = groups[key]
        g["display_names"].add(name)
        if row["entity_type"]:
            g["entity_types"].add(row["entity_type"])
        if row["position"] is not None:
            g["positions"].append(row["position"])
            if row["position"] == 1:
                g["first_place_count"] += 1
        if row["sentiment"]:
            g["sentiments"].append(row["sentiment"])
            if row["sentiment"] == "positive":
                g["positive_count"] += 1
        g["response_ids"].add(row["response_id"])
        g["prompt_ids"].add(row["prompt_id"])
        g["model_names"].add(row["model_name"])
        g["total_mentions"] += 1

    leaderboard = []
    for key, g in groups.items():
        # Pick the shortest non-truncated display name as the canonical label
        display_name = min(g["display_names"], key=lambda s: (len(s), s))
        avg_position = (
            round(sum(g["positions"]) / len(g["positions"]), 2)
            if g["positions"] else None
        )
        leaderboard.append({
            "normalized_key": key,
            "display_name": display_name,
            "variant_count": len(g["display_names"]),
            "variants": sorted(g["display_names"]),
            "entity_types": sorted(g["entity_types"]),
            "total_mentions": g["total_mentions"],
            "unique_responses": len(g["response_ids"]),
            "unique_prompts": len(g["prompt_ids"]),
            "models_mentioning": len(g["model_names"]),
            "avg_position": avg_position,
            "times_ranked_first": g["first_place_count"],
            "positive_mentions": g["positive_count"],
        })

    leaderboard.sort(
        key=lambda x: (-x["total_mentions"], x["avg_position"] or 999)
    )
    return leaderboard, noise


def print_leaderboard(leaderboard: list[dict], limit: int):
    print(f"\n{'='*90}")
    print(f"Normalized Leaderboard (top {min(limit, len(leaderboard))} of {len(leaderboard)} unique businesses)")
    print(f"{'='*90}\n")

    print(f"{'Rank':<5} {'Business':<40} {'Mentions':<10} "
          f"{'Variants':<10} {'Avg Pos':<10} {'#1s':<5}")
    print("-" * 90)
    for i, row in enumerate(leaderboard[:limit], 1):
        name = row["display_name"][:38]
        avg_pos = f"{row['avg_position']:.1f}" if row['avg_position'] else "-"
        print(f"{i:<5} {name:<40} {row['total_mentions']:<10} "
              f"{row['variant_count']:<10} {avg_pos:<10} "
              f"{row['times_ranked_first']:<5}")

    # Show variant detail for the top 5 — proves the merging worked
    print(f"\n{'='*90}")
    print("Variant merging detail (top 5 entries)")
    print(f"{'='*90}")
    for row in leaderboard[:5]:
        if row["variant_count"] > 1:
            print(f"\n{row['display_name']!r} ({row['total_mentions']} mentions) merged from:")
            for v in row["variants"]:
                print(f"  - {v}")
        else:
            print(f"\n{row['display_name']!r} ({row['total_mentions']} mentions) — single variant, no merging")


def print_noise(noise: list[dict]):
    if not noise:
        print("\n[No entries filtered as noise.]")
        return
    print(f"\n{'='*90}")
    print(f"Filtered as noise ({len(noise)} mentions)")
    print(f"{'='*90}")
    # Group by name for readability
    counts = defaultdict(int)
    for row in noise:
        counts[row["name"]] += 1
    for name, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {count}x  {name}")


def main():
    parser = argparse.ArgumentParser(description="Normalize extracted business names")
    parser.add_argument("--limit", type=int, default=25, help="Max rows to display")
    parser.add_argument("--client", type=str, default=None, help="Filter to one client_id")
    parser.add_argument("--show-noise", action="store_true",
                        help="Also print entries filtered out")
    args = parser.parse_args()

    rows = load_data(args.client)
    if not rows:
        print(f"[!] No data found. Did you run python run.py yet?")
        return

    print(f"Loaded {len(rows)} raw extraction rows from {DB_PATH}")
    if args.client:
        print(f"Filtered to client: {args.client}")

    leaderboard, noise = build_leaderboard(rows)
    print_leaderboard(leaderboard, args.limit)
    if args.show_noise:
        print_noise(noise)
    else:
        print(f"\n[{sum(1 for _ in noise)} mentions filtered as noise. "
              f"Use --show-noise to see them.]")


if __name__ == "__main__":
    main()