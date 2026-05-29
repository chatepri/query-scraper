"""
Main pipeline runner.

Flow per (prompt x model):
  1. Dispatcher sends prompt to model, returns ModelResponse
  2. Store ModelResponse to SQLite, get back response_id
  3. Judge analyzes response, returns list of Mentions
  4. Store Mentions to SQLite

After all prompts complete, print summary table.
"""
import time
import yaml
from pathlib import Path
from src.dispatchers.gemini import GeminiDispatcher
from src.dispatchers.perplexity import PerplexityDispatcher
from src.parsers.llm_judge import LLMJudge
from src.storage.sqlite_store import SQLiteStore


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_dispatchers(settings: dict) -> list:
    """Instantiate only the dispatchers marked enabled in settings."""
    dispatchers = []
    models_cfg = settings["models"]

    if models_cfg.get("gemini", {}).get("enabled"):
        try:
            dispatchers.append(GeminiDispatcher(models_cfg["gemini"]))
            print(f"  [+] Gemini ({models_cfg['gemini']['model_id']})")
        except Exception as e:
            print(f"  [!] Gemini init failed: {e}")

    if models_cfg.get("perplexity", {}).get("enabled"):
        try:
            dispatchers.append(PerplexityDispatcher(models_cfg["perplexity"]))
            print(f"  [+] Perplexity ({models_cfg['perplexity']['model_id']})")
        except Exception as e:
            print(f"  [!] Perplexity init failed: {e}")

    return dispatchers


def run_client(client_yaml_path: str, settings_path: str = "config/settings.yaml"):
    print(f"\n{'='*60}")
    print(f"Loading config: {client_yaml_path}")
    print(f"{'='*60}")

    client_config = load_yaml(client_yaml_path)
    settings = load_yaml(settings_path)

    client = client_config["client"]
    competitors = client_config["competitors"]
    prompts = client_config["prompts"]

    print(f"\nClient: {client['name']} ({client['id']})")
    print(f"Brand variants: {len(client['brand_variants'])}")
    print(f"Competitors tracked: {len(competitors)}")
    print(f"Prompts in this run: {len(prompts)}")

    print("\nInitializing dispatchers...")
    dispatchers = build_dispatchers(settings)
    if not dispatchers:
        print("  [!] No dispatchers available. Check API keys and settings.")
        return

    print("\nInitializing LLM judge...")
    judge = LLMJudge(settings["judge"])
    print(f"  [+] Claude judge ({settings['judge']['model_id']})")

    print("\nInitializing storage...")
    store = SQLiteStore(settings["storage"]["db_path"])
    print(f"  [+] SQLite at {settings['storage']['db_path']}")

    # The shape the judge expects
    client_brand = {
        "name": client["id"].upper(),
        "variants": client["brand_variants"],
    }

    delay = settings["run"]["delay_between_calls_seconds"]
    total_calls = len(prompts) * len(dispatchers)
    call_num = 0

    print(f"\n{'='*60}")
    print(f"Running {total_calls} API calls "
          f"({len(prompts)} prompts x {len(dispatchers)} models)")
    print(f"{'='*60}\n")

    for prompt in prompts:
        for dispatcher in dispatchers:
            call_num += 1
            print(f"[{call_num}/{total_calls}] {dispatcher.name} | "
                  f"{prompt['id']} | {prompt['text'][:60]}...")

            response = dispatcher.dispatch(
                client_id=client["id"],
                prompt_id=prompt["id"],
                prompt_text=prompt["text"],
            )

            if response.error:
                print(f"    [error] {response.error}")
                store.save_response(response)
                time.sleep(delay)
                continue

            response_id = store.save_response(response)

            mentions = judge.judge(
                response=response,
                client_brand=client_brand,
                competitors=competitors,
                response_id=response_id,
            )
            store.save_mentions(mentions)

            client_mention = next(
                (m for m in mentions if m.entity_type == "client"), None
            )
            if client_mention and client_mention.is_mentioned:
                print(f"    [+] {client['id']} mentioned "
                      f"(pos {client_mention.position}, "
                      f"sentiment {client_mention.sentiment})")
            else:
                print(f"    [-] {client['id']} not mentioned")

            time.sleep(delay)

    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}\n")
    summary = store.summary_by_entity(client["id"])

    print(f"{'Entity':<25} {'Type':<12} {'Model':<12} "
          f"{'Mentioned':<12} {'Avg Pos':<10}")
    print("-" * 75)
    for row in summary:
        mention_str = f"{row['mention_count']}/{row['total_prompts']}"
        avg_pos = f"{row['avg_position']}" if row['avg_position'] else "-"
        print(f"{row['entity_name']:<25} {row['entity_type']:<12} "
              f"{row['model_name']:<12} {mention_str:<12} {avg_pos:<10}")

    store.close()
    print(f"\nDone. Raw data in {settings['storage']['db_path']}\n")


if __name__ == "__main__":
    import sys
    client_path = sys.argv[1] if len(sys.argv) > 1 else "config/clients/yten.yaml"
    run_client(client_path)
