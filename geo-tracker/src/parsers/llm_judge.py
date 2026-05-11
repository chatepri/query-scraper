"""
LLM-based brand mention judge using Claude Haiku.

Takes a model response and the list of entities (client + competitors)
and returns structured mentions with sentiment, position, and confidence.

This replaces fragile regex/fuzzy matching with semantic understanding.
Cost: ~$0.002 per judgment call (Haiku is cheap).
"""
import os
import json
from typing import List
from src.models import ModelResponse, Mention


JUDGE_PROMPT = """You are analyzing a response from an AI search engine to determine which brands/companies are mentioned.

The original user question was:
{prompt}

The AI response was:
---
{response}
---

You need to evaluate whether each of these entities is mentioned in the response. Mentions can use any of the listed variants.

ENTITIES TO CHECK:
{entities_json}

For each entity, return:
- is_mentioned: true/false (true if ANY variant appears, even paraphrased)
- position: integer (1 = first brand mentioned in response, 2 = second, etc.) or null if not mentioned
- sentiment: "positive" | "neutral" | "negative" (how the response characterizes the brand) or null if not mentioned
- context_snippet: a 1-2 sentence excerpt from the response showing the mention, or null
- confidence: 0.0 to 1.0 (how confident you are in this judgment)

Return ONLY a JSON array, one object per entity, in the same order as ENTITIES TO CHECK. No prose, no markdown fencing.

Example output format:
[
  {{"entity_name": "BrandA", "is_mentioned": true, "position": 1, "sentiment": "positive", "context_snippet": "BrandA leads the market in...", "confidence": 0.95}},
  {{"entity_name": "BrandB", "is_mentioned": false, "position": null, "sentiment": null, "context_snippet": null, "confidence": 0.9}}
]
"""


class LLMJudge:
    def __init__(self, config: dict):
        from anthropic import Anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
        self.client = Anthropic(api_key=api_key)
        self.model_id = config["model_id"]
        self.timeout = config.get("timeout_seconds", 20)

    def judge(
        self,
        response: ModelResponse,
        client_brand: dict,
        competitors: list[dict],
        response_id: int,
    ) -> List[Mention]:
        """
        Args:
            response: the ModelResponse to analyze
            client_brand: {"name": "YTEN", "variants": [...]}
            competitors: [{"name": "...", "variants": [...]}, ...]
            response_id: the SQLite row ID of the stored response (FK)

        Returns:
            List of Mention objects, one per entity checked.
        """
        # Build the entities list - client first, then competitors
        entities = [
            {
                "name": client_brand["name"],
                "variants": client_brand["variants"],
                "type": "client",
            }
        ] + [
            {"name": c["name"], "variants": c["variants"], "type": "competitor"}
            for c in competitors
        ]

        # Edge case: response failed or is empty
        if not response.response_text or response.error:
            return [
                Mention(
                    response_id=response_id,
                    entity_name=e["name"],
                    entity_type=e["type"],
                    is_mentioned=False,
                    judge_confidence=1.0,
                )
                for e in entities
            ]

        prompt = JUDGE_PROMPT.format(
            prompt=response.prompt_text,
            response=response.response_text,
            entities_json=json.dumps(
                [{"name": e["name"], "variants": e["variants"]} for e in entities],
                indent=2,
            ),
        )

        try:
            msg = self.client.messages.create(
                model=self.model_id,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()

            # Strip code fences if the model added them despite instructions
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            judgments = json.loads(raw)

            mentions = []
            for i, entity in enumerate(entities):
                # Defensive: match by name in case order shifted
                j = next(
                    (x for x in judgments if x.get("entity_name") == entity["name"]),
                    judgments[i] if i < len(judgments) else {},
                )
                mentions.append(
                    Mention(
                        response_id=response_id,
                        entity_name=entity["name"],
                        entity_type=entity["type"],
                        is_mentioned=bool(j.get("is_mentioned", False)),
                        position=j.get("position"),
                        sentiment=j.get("sentiment"),
                        context_snippet=j.get("context_snippet"),
                        judge_confidence=j.get("confidence"),
                    )
                )
            return mentions

        except Exception as e:
            # If the judge fails, log and return empty mentions rather than crash
            print(f"  [judge error] {e}")
            return [
                Mention(
                    response_id=response_id,
                    entity_name=e_["name"],
                    entity_type=e_["type"],
                    is_mentioned=False,
                    judge_confidence=0.0,
                )
                for e_ in entities
            ]
