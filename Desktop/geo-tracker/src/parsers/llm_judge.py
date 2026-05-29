"""
LLM extractor using Claude Haiku.

Reads a model response and extracts EVERY business/organization mentioned.
Returns one ExtractedBusiness per entity found, with judge-assigned type,
position, sentiment, and a normalized name for deduplication.
"""
import os
import json
import re
from typing import List
from src.models import ModelResponse, ExtractedBusiness


EXTRACTOR_PROMPT = """You are analyzing a response from an AI search engine to extract every business or organization mentioned.

The original user question was:
{prompt}

The AI response was:
---
{response}
---

Extract EVERY distinct business, organization, university, non-profit, government program, or named service provider that is mentioned as relevant to the user's question. Do NOT extract:
- Generic terms ("AI consultants", "training firms")
- Software products or brand names UNLESS they are the answer (e.g. if the question is "which AI tools" then ChatGPT counts; if the question is "which firms train people on AI" then ChatGPT is just a tool reference, skip it)
- People's names UNLESS they are sole proprietors offering the service
- Cities, states, or geographic regions

For each extracted entity, return:
- name: exact text as it appears in the response
- normalized_name: lowercase, remove ALL of:
  - parenthetical suffixes like "(YTEN)", "(WNY)", "(UB)"
  - corporate suffixes "Inc", "LLC", "Corp", "Co", "Ltd", "L.P.A."
  - descriptive trailers like "Training Center", "Workforce Development", 
    "School of Management", "USA", "Buffalo"
  - leading "The "
  
Example: "Logical Operations Training Center" → "logical operations"
Example: "University at Buffalo (UB) – School of Management" → "university at buffalo"
Example: "NobleProg USA (Buffalo)" → "nobleprog"

- entity_type: one of "company" | "university" | "non_profit" | "government" | "unknown"
- position: integer (1 = first entity mentioned in response, 2 = second, etc.)
- sentiment: "positive" | "neutral" | "negative" (how the response characterizes them)
- context_snippet: 1-2 sentence quote from the response showing the mention
- confidence: 0.0 to 1.0 (how confident you are this is a real business mention, not noise)

Return ONLY a JSON array. No prose, no markdown fencing, no explanation. If no businesses are found, return [].

Example output format:
[
  {{"name": "Acme Consulting", "normalized_name": "acme consulting", "entity_type": "company", "position": 1, "sentiment": "positive", "context_snippet": "Acme Consulting leads in...", "confidence": 0.95}},
  {{"name": "State University", "normalized_name": "state university", "entity_type": "university", "position": 2, "sentiment": "neutral", "context_snippet": "...", "confidence": 0.9}}
]
"""


def normalize_fallback(name: str) -> str:
    """Backup normalization if the judge fails to provide it."""
    n = name.lower().strip()
    n = re.sub(r"\([^)]*\)", "", n)            # remove parentheticals
    n = re.sub(r"\b(inc|llc|corp|co|ltd)\.?\b", "", n)
    n = re.sub(r"^the\s+", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


class LLMJudge:
    def __init__(self, config: dict):
        from anthropic import Anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
        self.client = Anthropic(api_key=api_key)
        self.model_id = config["model_id"]
        self.timeout = config.get("timeout_seconds", 20)

    def extract(self, response: ModelResponse, response_id: int) -> List[ExtractedBusiness]:
        """Extract all businesses mentioned in the response.

        Args:
            response: the ModelResponse to analyze
            response_id: the SQLite row ID of the stored response (FK)
        """
        if not response.response_text or response.error:
            return []

        prompt = EXTRACTOR_PROMPT.format(
            prompt=response.prompt_text,
            response=response.response_text,
        )

        try:
            msg = self.client.messages.create(
                model=self.model_id,
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()

            # Strip code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            entities = json.loads(raw)
            if not isinstance(entities, list):
                return []

            results = []
            for e in entities:
                if not isinstance(e, dict) or not e.get("name"):
                    continue
                normalized = e.get("normalized_name") or normalize_fallback(e["name"])
                results.append(ExtractedBusiness(
                    response_id=response_id,
                    name=e["name"],
                    normalized_name=normalized,
                    entity_type=e.get("entity_type"),
                    position=e.get("position"),
                    sentiment=e.get("sentiment"),
                    context_snippet=e.get("context_snippet"),
                    confidence=e.get("confidence"),
                ))
            return results

        except Exception as e:
            print(f"  [extractor error] {e}")
            return []