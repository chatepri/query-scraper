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
What to EXCLUDE (do not extract):
- Software platforms or SaaS products mentioned as TOOLS that providers
  INTEGRATE WITH or USE in their work. Examples of phrases that signal this:
  "connects to X", "integrates X with Y", "audits your tech stack including X",
  "uses built-in AI features in platforms like X", "supports X, Y, Z".
  If the entity is described as something the consultant USES, CONNECTS TO,
  AUDITS, or HELPS YOU SET UP — it's a tool reference, not an answer to
  "who provides this service". SKIP these.
  Examples to skip: Salesforce, HubSpot, Microsoft Copilot, Google Workspace,
  Zapier, TechSoup, Raiser's Edge — when mentioned as integration targets.
  These ARE valid extractions if the prompt itself is asking about THEM
  (e.g. "best CRM platforms" → Salesforce is the answer).
- Buildings, office complexes, venues, or addresses (e.g. "Regus Key Center", "Tri-Main Center", "Northpointe Pkwy")
- Government programs or funding initiatives (e.g. "Empire AI", "Empire AI Consortium")
- Cities, states, regions, or geographic areas
- Generic category terms ("AI consultants", "training firms")
- Software products or tools UNLESS they ARE the answer (if the question asks "which firms train people", then ChatGPT/Gemini/Copilot are just tools mentioned in passing — skip them)
- Entities mentioned ONLY as a partner, sponsor, parent platform, or client of another provider — NOT as a standalone option. For example, if the text says "In partnership with Microsoft's TechSpark and IBM SkillsBuild, TechBuffalo provides...", then TechBuffalo is an answer but Microsoft and IBM are partners — skip Microsoft and IBM. Use the surrounding context to judge whether each entity is being recommended in its own right.
- Software platforms or SaaS products mentioned as TOOLS that providers INTEGRATE WITH or USE in their work. Examples of phrases that signal this: "connects to X", "integrates X with Y", "audits your tech stack including X", "uses built-in AI features in platforms like X", "supports X, Y, Z". If the entity is described as something the consultant USES, CONNECTS TO, AUDITS, or HELPS YOU SET UP — it's a tool reference, not an answer to "who provides this service". SKIP these. Examples to skip: Salesforce, HubSpot, Microsoft Copilot, Google Workspace, Zapier, TechSoup, Raiser's Edge — when mentioned as integration targets. These ARE valid extractions if the prompt itself is asking about THEM (e.g. "best CRM platforms" → Salesforce is the answer).
- People's names UNLESS they are a sole proprietor offering the service under their own name
- Professional rating directories, lawyer-finding platforms, attorney search sites, comparison websites, or peer-review services. These appear in responses as places consumers go TO FIND providers — not as providers themselves. Examples to skip: Super Lawyers, Avvo, Martindale-Hubbell, Best Lawyers, Justia, Justia Lawyer Directory, Expertise.com, U.S. News & World Report, Best Law Firms, FindLaw, Lawyers.com, Nolo. These are valid extractions only if the prompt itself asks about rating directories (e.g. "best lawyer rating sites" → Super Lawyers is the answer).
- Bar associations, professional licensing bodies, industry guilds, or trade organizations. Examples to skip: Ohio State Bar Association, Columbus Bar Association, Cleveland Metropolitan Bar Association, Cincinnati Bar Association, American Bar Association, American Medical Association. These appear as referral resources or licensing context, not as competing providers.
- Government agencies, courts, police departments, emergency services, regulatory bodies, and licensing/compensation boards mentioned as referral context, official-action recipients, or background information. Examples to skip: Ohio State Highway Patrol, Columbus Division of Police, Franklin County Court of Common Pleas, Bureau of Workers' Compensation (BWC), Department of Insurance, Better Business Bureau, when they appear as "call X after an accident" / "file with Y" / "regulated by Z". Government entities ARE valid extractions if the prompt asks for them (e.g. "where to file workers comp claim Ohio" → BWC is the answer).
- News publications, generic media outlets, or third-party publishers UNLESS the prompt is asking about media coverage. Examples to skip: U.S. News & World Report (also covered under rating directories), Forbes, Bloomberg, when they appear as "as featured in X" or "ranked by Y".
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