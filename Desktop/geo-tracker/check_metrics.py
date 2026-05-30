"""
Smoke test for visibility_metrics against any client's data.

Usage:
  python check_metrics.py <client_id> <business_name> [alias1,alias2,...]

Examples:
  python check_metrics.py yten "You're The Expert Now" YTEN,YEN,Y-TEN
  python check_metrics.py acme_law "Acme Law Group"
"""
import sys
from src.visibility_metrics import compute_metrics


def main():
    if len(sys.argv) < 3:
        print("Usage: python check_metrics.py <client_id> <business_name> [aliases]")
        print("Example: python check_metrics.py yten \"You're The Expert Now\" YTEN,YEN")
        sys.exit(1)

    client_id = sys.argv[1]
    business_name = sys.argv[2]
    aliases = sys.argv[3].split(",") if len(sys.argv) > 3 else None

    m = compute_metrics(
        client_id=client_id,
        business_name=business_name,
        extra_aliases=aliases,
    )

    print(f"\n=== Hero Metrics ({client_id}) ===\n")
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
        print(f"  Rank:               not ranked ({m.total_competitors} competitors)")

    import json
    print("\n--- Strip dict ---")
    print(json.dumps(m.as_strip(), indent=2))


if __name__ == "__main__":
    main()