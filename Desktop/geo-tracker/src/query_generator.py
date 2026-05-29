"""
Auto-generate candidate queries from a business name + website URL.

Pipeline:
  1. Scrape the website's homepage + a few common internal pages
  2. Strip HTML, extract clean text
  3. Send to Claude Haiku with structured instructions to:
     - Infer industry, services, geography, audience
     - Generate 5 prospect-style queries

Returns a BusinessProfile the user reviews/edits before the queries
go into the dispatcher pipeline. The output cleanly maps to the
client YAML structure — see save_as_client_yaml() helper.
"""
import os
import re
import json
import html as _html
import requests
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urlparse, urljoin


# Pages we try beyond the homepage. Best-effort — missing pages are silent.
INTERNAL_PATHS = ["/about", "/about-us", "/services", "/what-we-do", "/contact"]


@dataclass
class BusinessProfile:
    """The full result returned to the front end / CLI for user review."""
    name: str
    url: str
    industry: Optional[str] = None
    services: list[str] = field(default_factory=list)
    geography: Optional[str] = None
    audience: Optional[str] = None
    proposed_queries: list[str] = field(default_factory=list)
    scraped_pages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _fetch(url: str, timeout: int = 10) -> Optional[str]:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (GEO-tracker query-generator)"}
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass
    return None


def _extract_text(html: str, max_chars: int = 8000) -> str:
    """Strip tags + scripts/styles/comments, decode entities, collapse whitespace."""
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", html)
    text = _html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def scrape_site(url: str, max_pages: int = 4) -> tuple[str, list[str], list[str]]:
    """Fetch homepage + a few internal pages. Returns (text, pages_fetched, warnings)."""
    url = _normalize_url(url)
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    pages_fetched = []
    warnings = []
    chunks = []

    home_html = _fetch(url)
    if not home_html:
        warnings.append(f"Could not fetch homepage: {url}")
        return "", [], warnings
    chunks.append(f"[HOMEPAGE]\n{_extract_text(home_html)}")
    pages_fetched.append(url)

    for path in INTERNAL_PATHS:
        if len(pages_fetched) >= max_pages:
            break
        page_url = urljoin(base, path)
        page_html = _fetch(page_url)
        if page_html:
            chunks.append(f"[{path.upper()}]\n{_extract_text(page_html, max_chars=3000)}")
            pages_fetched.append(page_url)

    return "\n\n".join(chunks), pages_fetched, warnings


GENERATOR_PROMPT = """You are analyzing a business's website to identify what they do and generate prospect-style search queries that real customers would use to find providers like them.

Business name: {name}
Website URL: {url}

Scraped website text (homepage and a few internal pages, truncated):
---
{site_text}
---

## Your task

1. Identify the business profile:
   - industry: short descriptor of the sector (e.g. "personal injury law", "Generative AI consulting and training", "wind turbine blade decommissioning", "pest control")
   - services: 3-5 specific services they offer
   - geography: where they primarily serve (city, state, region, or "national" / "global")
   - audience: their primary customer type (e.g. "small businesses and nonprofits", "individual injury victims", "industrial wind farm operators")

2. Generate exactly 5 queries that a real prospect would type into an AI search engine WHEN THEY ARE TRYING TO FIND AND HIRE A PROVIDER. The queries should:
   - Trigger the model to return a LIST OF BUSINESSES, not advice or how-to instructions
   - Be COMMERCIAL INTENT: someone looking to spend money, not someone seeking knowledge
   - REJECT informational patterns like "how do I...", "what is...", "tips for..." — those return guides, not provider lists
   - Be how a CUSTOMER would search, not how the business describes itself
   - Mix structural patterns: some "best X in Y", some bare service descriptions ("commercial HVAC repair"), some "who offers X"
   - Be mostly UNBRANDED discovery (we're measuring visibility against competitors)
   - Include geography where customers would naturally search that way
   - Vary in specificity from broad to narrow
   - Be local-leaning by default (local dominance before national)

Examples of GOOD prompts (return business lists):
   - "best personal injury lawyers in Cleveland Ohio"
   - "generative AI consultants for nonprofits"
   - "wind turbine blade decommissioning services"
   - "who offers Microsoft Copilot training for enterprise"
   - "top pest control company in Ann Arbor Michigan"

Examples of BAD prompts (return guides, not lists — DO NOT GENERATE THESE):
   - "how to implement AI responsibly"
   - "what is generative engine optimization"
   - "tips for adopting AI in small business"

## Output

Return ONLY valid JSON. No prose. No markdown fencing.

{{
  "industry": "...",
  "services": ["...", "...", "..."],
  "geography": "...",
  "audience": "...",
  "proposed_queries": ["...", "...", "...", "...", "..."]
}}
"""


def generate_queries(
    name: str,
    url: str,
    model_id: str = "claude-haiku-4-5-20251001",
) -> BusinessProfile:
    """End-to-end: scrape -> infer -> propose queries.

    Never raises on scrape or LLM failure — failures are recorded in
    profile.warnings so the front end can surface them to the user.
    """
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")

    profile = BusinessProfile(name=name, url=_normalize_url(url))

    site_text, pages, warnings = scrape_site(profile.url)
    profile.scraped_pages = pages
    profile.warnings.extend(warnings)

    if not site_text:
        profile.warnings.append("No site text retrieved; cannot generate queries.")
        return profile

    client = Anthropic(api_key=api_key)
    prompt = GENERATOR_PROMPT.format(name=name, url=profile.url, site_text=site_text)

    try:
        msg = client.messages.create(
            model=model_id,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        profile.industry = data.get("industry")
        profile.services = data.get("services") or []
        profile.geography = data.get("geography")
        profile.audience = data.get("audience")
        profile.proposed_queries = data.get("proposed_queries") or []
    except Exception as e:
        profile.warnings.append(f"LLM inference failed: {type(e).__name__}: {e}")

    return profile


def save_as_client_yaml(profile: BusinessProfile, path: str, client_id: str) -> None:
    """Write a runnable client YAML from a profile + user-confirmed queries."""
    import yaml
    from datetime import datetime

    cfg = {
        "client": {"id": client_id, "name": profile.name},
        "variables": {
            "industry": profile.industry or "",
            "geography": profile.geography or "",
            "audience": profile.audience or "",
        },
        "prompts": list(profile.proposed_queries),
    }

    header = (
        f"# AUTO-GENERATED DRAFT — review and edit before running\n"
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"# Source: scrape of {profile.url} + LLM inference\n"
        f"#\n"
        f"# Next steps:\n"
        f"#   1. Edit the prompts list below to taste\n"
        f"#   2. Move this file to config/clients/<name>.yaml when ready\n"
        f"#   3. Run: python run.py config/clients/<name>.yaml --mode preview\n\n"
    )

    with open(path, "w") as f:
        f.write(header)
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)