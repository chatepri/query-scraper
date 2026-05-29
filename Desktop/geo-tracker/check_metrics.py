"""
One-shot smoke test: run compute_metrics against your actual YTEN data
and print the three hero numbers. Confirms everything wires up correctly
against the real SQLite before the Streamlit layer goes on top.
"""
from src.visibility_metrics import compute_metrics

m = compute_metrics(
    client_id="yten",
    business_name="You're The Expert Now",
    extra_aliases=["YTEN", "YEN", "Y-TEN"],
)

print("\n=== Hero Metrics (YTEN) ===\n")
print(f"  Business:           {m.business_name}")
print(f"  Matched normalized: {m.matched_normalized_names}")
print()
print(f"  Mention rate:       {m.mention_rate*100:.1f}%  "
      f"({m.mentions_count} of {m.total_responses} responses)")
if m.top3_rate is not None:
    print(f"  Top-3 rate:         {m.top3_rate*100:.1f}%  "
          f"({m.top3_count} of {m.total_user_mentions} mentions)")
else:
    print(f"  Top-3 rate:         n/a (no positioned mentions yet)")
if m.rank:
    print(f"  Rank:               #{m.rank} of {m.total_competitors} competitors")
else:
    print(f"  Rank:               not ranked ({m.total_competitors} competitors found)")
print()

print("--- Strip dict (what Streamlit will read) ---")
import json
print(json.dumps(m.as_strip(), indent=2))