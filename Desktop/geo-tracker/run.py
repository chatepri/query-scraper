"""
Entry point for the GEO tracker.

Usage:
  python run.py                                          # default: preview mode on yten.yaml
  python run.py config/clients/acme.yaml                 # different client, preview mode
  python run.py --mode test                              # dev mode (cheap, fast)
  python run.py --mode audit config/clients/acme.yaml    # Pro deep audit
  python run.py --dry-run                                # preview prompts, no API calls
"""
import argparse
from dotenv import load_dotenv

load_dotenv()

from src.runner import run_client, load_prompts, load_yaml


def dry_run(client_path: str):
    cfg = load_yaml(client_path)
    prompts, warnings = load_prompts(cfg)
    print(f"\nDRY RUN — {cfg['client']['name']} ({client_path})")
    print(f"{'='*60}")
    print(f"{len(prompts)} prompts would be sent to each model:\n")
    for p in prompts:
        print(f"  [{p['id']}] ({p['source']:8}) {p['text']}")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  [!] {w}")
    print("\nNo API calls made.\n")


def main():
    parser = argparse.ArgumentParser(description="GEO tracker runner")
    parser.add_argument("client_path", nargs="?",
                        default="config/clients/yten.yaml",
                        help="Path to client YAML")
    parser.add_argument("--mode", choices=["test", "preview", "audit"],
                        default=None,
                        help="Iteration mode (overrides settings.default_mode)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview the prompt set, do not call APIs")
    args = parser.parse_args()

    if args.dry_run:
        dry_run(args.client_path)
        return

    settings = load_yaml("config/settings.yaml")
    mode = args.mode or settings["run"].get("default_mode", "preview")
    iterations = settings["run"]["modes"][mode]

    print(f"\nMode: {mode} ({iterations} iterations per prompt per model)")
    run_client(args.client_path, iterations_override=iterations)


if __name__ == "__main__":
    main()