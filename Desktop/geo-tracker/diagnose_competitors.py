"""
Diagnose: why is total_competitors so high? Show the bottom of the
leaderboard and group with more aggressive rules to see how many
ACTUAL distinct entities exist.
"""
import sqlite3
import re
from collections import defaultdict


def aggressive(name: str) -> str:
    """Diagnostic-only stricter normalization."""
    n = re.sub(r"\s*\([^)]*\)\s*", " ", name)
    n = re.sub(r"\s*[\u2013\u2014-]\s+.+$", "", n)
    n = re.sub(r"^the\s+", "", n, flags=re.I)
    n = re.sub(
        r"\s+(training center|training|workforce development( office)?|"
        r"school of management|usa|center|consortium|group|firm|"
        r"bootcamp|institute|college|university|services|service|"
        r"office|offices|llc|inc|corp|company|co|ltd|p\.?c\.?|l\.?p\.?a\.?)"
        r"\b.*$", "", n, flags=re.I)
    n = n.lower().strip(" ,.-&")
    n = re.sub(r"\s+", " ", n)
    return n


conn = sqlite3.connect("data/geo_tracker.db")
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT eb.normalized_name, COUNT(*) AS n
    FROM extracted_businesses eb
    JOIN runs r ON r.id = eb.response_id
    WHERE r.client_id = 'yten' AND r.error IS NULL
    GROUP BY eb.normalized_name
    ORDER BY n DESC
""").fetchall()

print(f"Currently: {len(rows)} distinct normalized_names\n")
print("Top 15 (likely real competitors):")
for r in rows[:15]:
    print(f"  {r['n']:>3}  {r['normalized_name']}")

print(f"\nBottom 20 (likely the inflation):")
for r in rows[-20:]:
    print(f"  {r['n']:>3}  {r['normalized_name']}")

regrouped = defaultdict(int)
for r in rows:
    regrouped[aggressive(r["normalized_name"])] += r["n"]

print(f"\nAfter aggressive re-normalization: {len(regrouped)} distinct entities")
print(f"  (reduction of {len(rows) - len(regrouped)})\n")
print("Top 15 after aggressive regrouping:")
for k, n in sorted(regrouped.items(), key=lambda x: -x[1])[:15]:
    print(f"  {n:>3}  {k}")

conn.close()