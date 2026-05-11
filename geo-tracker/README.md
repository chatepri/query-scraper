# GEO Tracker (v1)

Lightweight scraper that runs a defined set of prompts against multiple AI models, detects brand mentions using an LLM judge, and stores everything in SQLite for analysis.

**v1 scope:** Gemini + Perplexity, API-only, single-client manual runs.

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create your env file
cp .env.example .env
# Then edit .env and add your real API keys

# 3. Run the pilot
python run.py
```

That runs the default client config at `config/clients/yten.yaml`.

## Project layout

```
geo-tracker/
├── config/
│   ├── clients/yten.yaml      ← edit prompts, brand variants, competitors here
│   └── settings.yaml          ← model IDs, timeouts, judge config
├── src/
│   ├── dispatchers/           ← one file per provider
│   ├── parsers/llm_judge.py   ← Claude Haiku judges each response
│   ├── storage/sqlite_store.py
│   ├── models.py              ← shared dataclasses
│   └── runner.py              ← orchestration
├── data/geo_tracker.db        ← SQLite (auto-created)
├── reports/                   ← future: .docx outputs
└── run.py
```

## Adding a new client

Copy `config/clients/yten.yaml`, rename, edit. No code changes needed.

## Adding a new model (v2)

1. Create `src/dispatchers/newmodel.py` that subclasses `BaseDispatcher`
2. Enable it in `config/settings.yaml`
3. Register it in `src/runner.py` `build_dispatchers()`

## Querying results

The DB is just SQLite. Examples:

```sql
-- Mention rate per entity per model
SELECT m.entity_name, r.model_name,
       SUM(m.is_mentioned) AS hits,
       COUNT(*) AS total,
       ROUND(100.0 * SUM(m.is_mentioned) / COUNT(*), 1) AS hit_rate_pct
FROM mentions m JOIN runs r ON r.id = m.response_id
GROUP BY m.entity_name, r.model_name
ORDER BY hit_rate_pct DESC;

-- Most cited domains
SELECT
  REPLACE(REPLACE(REPLACE(url, 'https://', ''), 'http://', ''),
          'www.', '') AS domain,
  COUNT(*) AS citation_count
FROM citations
GROUP BY domain
ORDER BY citation_count DESC
LIMIT 20;
```

## Cost estimate

For one full run of YTEN config (15 prompts x 2 models + 30 judge calls):
- Gemini 2.5 Flash: ~$0.01
- Perplexity Sonar: ~$0.05
- Claude Haiku judge: ~$0.05
- **Total: ~$0.11 per run**

Daily runs for a month: ~$3.30.
