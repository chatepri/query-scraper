"""
Main pipeline runner.

Flow per (prompt x model x iteration):
  1. Dispatcher sends prompt to model, returns ModelResponse with iteration tag
  2. Store response to SQLite, get response_id
  3. Judge extracts all businesses from response
  4. Store extractions to SQLite

Repeat runs (runs_per_prompt) capture model nondeterminism: the same prompt
sent multiple times produces different responses, and the FREQUENCY of
mentions across repeats is a stronger signal than a single binary outcome.

Per-model overrides via models.<name>.runs_per_prompt take precedence over
the global run.runs_per_prompt default.
"""
import time
import yaml
import itertools
import re
from pathlib import Path
from src.dispatchers.gemini import GeminiDispatcher
from src.dispatchers.perplexity import PerplexityDispatcher
from src.parsers.llm_judge import LLMJudge
from src.storage.sqlite_store import SQLiteStore

def _substitute(text: str, variables: dict) -> str:
    """Fill {placeholder} tokens from variables. Leaves unknown placeholders
    intact so load_prompts can detect and warn about them."""
    def repl(match):
        return str(variables.get(match.group(1), match.group(0)))
    return re.sub(r"\{(\w+)\}", repl, text)


def _find_unfilled(text: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", text)


def load_prompts(client_config: dict) -> tuple[list[dict], list[str]]:
    """Build the full prompt list from explicit prompts + sweep expansions.

    Returns (prompts, warnings) where each prompt is {id, text, source}.
    Deduplicates by normalized text. IDs assigned after dedup.
    """
    variables = dict(client_config.get("variables", {}))
    variables.setdefault("name", client_config["client"]["name"])

    seen = set()
    prompts = []
    warnings = []

    for raw in client_config.get("prompts", []):
        text = _substitute(raw, variables)
        unfilled = _find_unfilled(text)
        if unfilled:
            warnings.append(f"explicit prompt has unfilled {unfilled}: {raw!r}")
        norm = text.strip().lower()
        if norm in seen:
            continue
        seen.add(norm)
        prompts.append({"text": text, "source": "explicit"})

    for sweep in client_config.get("sweeps", []):
        pattern = sweep["pattern"]
        dims = {k: v for k, v in sweep.items() if k != "pattern"}
        keys = list(dims.keys())
        for combo in itertools.product(*[dims[k] for k in keys]):
            local = dict(variables)
            local.update(dict(zip(keys, combo)))
            text = _substitute(pattern, local)
            unfilled = _find_unfilled(text)
            if unfilled:
                warnings.append(f"sweep prompt has unfilled {unfilled}: {pattern!r}")
            norm = text.strip().lower()
            if norm in seen:
                continue
            seen.add(norm)
            prompts.append({"text": text, "source": "sweep"})

    for i, p in enumerate(prompts, 1):
        p["id"] = f"p{i:03d}"

    return prompts, warnings

def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_dispatchers(settings: dict) -> list:
    """Returns list of (dispatcher, runs_per_prompt) tuples."""
    dispatchers = []
    models_cfg = settings["models"]
    default_runs = settings.get("run", {}).get("runs_per_prompt", 1)

    if models_cfg.get("gemini", {}).get("enabled"):
        try:
            d = GeminiDispatcher(models_cfg["gemini"])
            runs = models_cfg["gemini"].get("runs_per_prompt", default_runs)
            dispatchers.append((d, runs))
            grounding = "grounded" if models_cfg["gemini"].get("enable_grounding") else "ungrounded"
            print(f"  [+] Gemini ({models_cfg['gemini']['model_id']}, {grounding}, {runs} runs/prompt)")
        except Exception as e:
            print(f"  [!] Gemini init failed: {e}")

    if models_cfg.get("perplexity", {}).get("enabled"):
        try:
            d = PerplexityDispatcher(models_cfg["perplexity"])
            runs = models_cfg["perplexity"].get("runs_per_prompt", default_runs)
            dispatchers.append((d, runs))
            print(f"  [+] Perplexity ({models_cfg['perplexity']['model_id']}, {runs} runs/prompt)")
        except Exception as e:
            print(f"  [!] Perplexity init failed: {e}")

    return dispatchers


def run_client(client_yaml_path: str, 
               settings_path: str = "config/settings.yaml",
               iterations_override: int = None):
    print(f"\n{'='*60}")
    print(f"Loading config: {client_yaml_path}")
    print(f"{'='*60}")

    client_config = load_yaml(client_yaml_path)
    settings = load_yaml(settings_path)
    if iterations_override is not None:
        # Mode-based override from run.py CLI flag
        settings["run"]["runs_per_prompt"] = iterations_override

    client = client_config["client"]
    prompts, prompt_warnings = load_prompts(client_config)
    if prompt_warnings:
        print("\n  [!] Prompt warnings:")
        for w in prompt_warnings:
            print(f"      {w}")

    print(f"\nClient: {client['name']} ({client['id']})")
    print(f"Prompts in this run: {len(prompts)}")

    print("\nInitializing dispatchers...")
    dispatcher_specs = build_dispatchers(settings)
    if not dispatcher_specs:
        print("  [!] No dispatchers available. Check API keys and settings.")
        return

    print("\nInitializing extractor...")
    judge = LLMJudge(settings["judge"])
    print(f"  [+] Claude extractor ({settings['judge']['model_id']})")

    print("\nInitializing storage...")
    store = SQLiteStore(settings["storage"]["db_path"])
    print(f"  [+] SQLite at {settings['storage']['db_path']}")

    delay = settings["run"]["delay_between_calls_seconds"]
    total_calls = sum(len(prompts) * runs for _, runs in dispatcher_specs)
    call_num = 0

    print(f"\n{'='*60}")
    print(f"Running {total_calls} API calls total")
    print(f"  {len(prompts)} prompts x {len(dispatcher_specs)} models")
    print(f"  Repeat runs vary per model (see above)")
    print(f"{'='*60}\n")

    for prompt in prompts:
        for dispatcher, runs_per_prompt in dispatcher_specs:
            for iteration in range(1, runs_per_prompt + 1):
                call_num += 1
                print(f"[{call_num}/{total_calls}] {dispatcher.name} | "
                      f"{prompt['id']} | iter {iteration}/{runs_per_prompt} | "
                      f"{prompt['text'][:50]}...")

                response = dispatcher.dispatch(
                    client_id=client["id"],
                    prompt_id=prompt["id"],
                    prompt_text=prompt["text"],
                )
                response.run_iteration = iteration

                if response.error:
                    print(f"    [error] {response.error}")
                    store.save_response(response)
                    time.sleep(delay)
                    continue

                response_id = store.save_response(response)
                businesses = judge.extract(response, response_id)
                store.save_extractions(businesses)

                print(f"    [+] extracted {len(businesses)} businesses")
                if businesses and iteration == 1:
                    for b in businesses[:3]:
                        print(f"        {b.position}. {b.name} ({b.entity_type})")
                    if len(businesses) > 3:
                        print(f"        ... and {len(businesses) - 3} more")

                time.sleep(delay)

    print(f"\n{'='*60}")
    print("Leaderboard — Top businesses across all prompts, models, iterations")
    print(f"{'='*60}\n")
    rows = store.leaderboard(client["id"], limit=25)

    if not rows:
        print("No businesses extracted. Check raw responses with inspect_response.py")
    else:
        print(f"{'Rank':<5} {'Business':<35} {'Mentions':<10} "
              f"{'Models':<8} {'Avg Pos':<10} {'#1s':<5}")
        print("-" * 80)
        for i, row in enumerate(rows, 1):
            name = row["display_name"][:33]
            avg_pos = f"{row['avg_position']:.1f}" if row['avg_position'] else "-"
            print(f"{i:<5} {name:<35} {row['total_mentions']:<10} "
                  f"{row['models_mentioning']:<8} {avg_pos:<10} "
                  f"{row['times_ranked_first']:<5}")

    store.close()
    print(f"\nDone. Raw data in {settings['storage']['db_path']}\n")


if __name__ == "__main__":
    import sys
    client_path = sys.argv[1] if len(sys.argv) > 1 else "config/clients/yten.yaml"
    run_client(client_path)