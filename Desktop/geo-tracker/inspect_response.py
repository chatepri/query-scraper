"""
Diagnostic: inspect stored responses and their extracted businesses.

Usage:
  python inspect_response.py                    # latest 5 runs
  python inspect_response.py p003               # latest p003 from all models
  python inspect_response.py p003 gemini        # latest p003 from gemini only
"""
import sys
import sqlite3
import json
from pathlib import Path

DB_PATH = "data/geo_tracker.db"


def inspect(prompt_id: str = None, model_name: str = None):
    if not Path(DB_PATH).exists():
        print(f"[!] Database not found at {DB_PATH}. Run python run.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    where = []
    params = []
    if prompt_id:
        where.append("prompt_id = ?")
        params.append(prompt_id)
    if model_name:
        where.append("model_name = ?")
        params.append(model_name)
    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    runs = conn.execute(
        f"SELECT * FROM runs {where_clause} ORDER BY timestamp DESC LIMIT 10",
        params,
    ).fetchall()

    if not runs:
        print(f"[!] No runs found matching prompt_id={prompt_id} model={model_name}")
        return

    for run in runs:
        print("\n" + "=" * 70)
        print(f"RUN #{run['id']} | {run['prompt_id']} | {run['model_name']} "
              f"({run['model_id']})")
        print(f"Timestamp: {run['timestamp']}  |  Latency: {run['latency_ms']} ms")
        print(f"Grounding: {run['grounding_mode'] or 'n/a'}")
        print("=" * 70)

        print(f"\nPROMPT:\n  {run['prompt_text']}")

        if run["error"]:
            print(f"\n[!] ERROR: {run['error']}")
            continue

        if run["raw_payload"]:
            try:
                payload = json.loads(run["raw_payload"])
                queries = payload.get("search_queries", [])
                if queries:
                    print(f"\nSEARCH QUERIES GEMINI USED:")
                    for q in queries:
                        print(f"  - {q}")
            except json.JSONDecodeError:
                pass

        cites = conn.execute(
            "SELECT * FROM citations WHERE response_id = ?", (run["id"],)
        ).fetchall()
        if cites:
            print(f"\nCITATIONS ({len(cites)}):")
            for c in cites[:10]:
                title = c["title"] or "(no title)"
                print(f"  - {title}")
                print(f"    {c['url']}")
            if len(cites) > 10:
                print(f"  ... and {len(cites) - 10} more")

        print(f"\nRESPONSE TEXT (first 2000 chars):")
        print("-" * 70)
        print((run["response_text"] or "")[:2000])
        if len(run["response_text"] or "") > 2000:
            print(f"... [truncated, full length: {len(run['response_text'])} chars]")
        print("-" * 70)

        businesses = conn.execute(
            """SELECT name, normalized_name, entity_type, position,
                      sentiment, confidence, context_snippet
               FROM extracted_businesses WHERE response_id = ?
               ORDER BY position""",
            (run["id"],),
        ).fetchall()

        print(f"\nEXTRACTED BUSINESSES ({len(businesses)}):")
        if not businesses:
            print("  (none)")
        for b in businesses:
            conf = f" conf={b['confidence']:.2f}" if b['confidence'] is not None else ""
            print(f"  {b['position']:>2}. {b['name']:<40} "
                  f"[{b['entity_type']}] sentiment={b['sentiment']}{conf}")
            if b["context_snippet"]:
                print(f"      \"{b['context_snippet'][:120]}\"")

    conn.close()


if __name__ == "__main__":
    prompt_id = sys.argv[1] if len(sys.argv) > 1 else None
    model_name = sys.argv[2] if len(sys.argv) > 2 else None
    inspect(prompt_id, model_name)