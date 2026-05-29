# AUTO-GENERATED DRAFT — review and edit before running
# Generated: 2026-05-29 15:42
# Source: scrape of https://youretheexpertnow.com + Claude Haiku inference
#
# Next steps:
#   1. Edit the prompts list below to taste
#   2. Move this file to config/clients/<name>.yaml when ready
#   3. Run: python run.py config/clients/<name>.yaml --mode preview

"""
CLI for the query auto-generator.

Usage:
  python generate_queries.py "You're The Expert Now" youretheexpertnow.com
  python generate_queries.py "Acme Law" acmelaw.com --save config/clients/acme.yaml --id acme

The output is meant for human review. After running:
  1. Read the proposed queries
  2. Edit them in your editor (or pass --save and edit the YAML)
  3. Run python run.py --dry-run config/clients/<id>.yaml to verify
  4. Run python run.py config/clients/<id>.yaml to execute
"""
import argparse
from dotenv import load_dotenv

load_dotenv()

from src.query_generator import generate_queries, save_as_client_yaml


def main():
    p = argparse.ArgumentParser(description="Auto-generate candidate queries")
    p.add_argument("name", help="Business name (e.g. 'You\\'re The Expert Now')")
    p.add_argument("url", help="Website URL (with or without https://)")
    p.add_argument("--save", help="Write a client YAML to this path")
    p.add_argument("--id", default=None, help="client_id when saving (default: derived from name)")
    args = p.parse_args()

    print(f"\nGenerating queries for: {args.name}")
    print(f"  URL: {args.url}\n")
    print("Scraping website + inferring profile (this takes ~10-15 seconds)...")

    profile = generate_queries(args.name, args.url)

    print(f"\n--- Pages scraped ({len(profile.scraped_pages)}) ---")
    for p_ in profile.scraped_pages:
        print(f"  {p_}")

    if profile.warnings:
        print(f"\n--- Warnings ({len(profile.warnings)}) ---")
        for w in profile.warnings:
            print(f"  [!] {w}")

    print(f"\n--- Inferred profile ---")
    print(f"  Industry:   {profile.industry}")
    print(f"  Services:   {', '.join(profile.services) if profile.services else '-'}")
    print(f"  Geography:  {profile.geography}")
    print(f"  Audience:   {profile.audience}")

    print(f"\n--- Proposed queries (review and edit) ---")
    if not profile.proposed_queries:
        print("  (none generated)")
    for i, q in enumerate(profile.proposed_queries, 1):
        print(f"  {i}. {q}")

    if args.save:
        from datetime import datetime
        client_id = args.id or args.name.lower().replace(" ", "_").replace("'", "")[:32]

        # If --save is just a directory or omitted, build a timestamped path
        if args.save.endswith("/") or args.save.endswith("\\") or args.save in ("auto", "."):
            ts = datetime.now().strftime("%Y_%m_%d_%H_%M")
            path = f"config/clients/auto/{client_id}_{ts}.yaml"
        else:
            path = args.save

        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        save_as_client_yaml(profile, path, client_id)
        print(f"\nWrote client config -> {path}")
        print(f"Edit the prompts there, then: python run.py {args.save} --dry-run")


if __name__ == "__main__":
    main()