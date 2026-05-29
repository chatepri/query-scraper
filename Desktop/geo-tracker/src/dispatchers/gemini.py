"""
Gemini dispatcher with Google Search grounding support.

Reads `enable_grounding` flag from settings.yaml.
When grounded:
  - Gemini executes Google Search before answering (behaves like consumer app)
  - Citations come back via groundingMetadata.groundingChunks
  - Each grounded request is billable (free tier: 500/day on Gemini 3.x Flash)

When ungrounded:
  - Pure training-data response
  - No citations
  - Measures "knowledge presence" rather than "visibility"

Install: pip install google-genai
Get API key: https://aistudio.google.com/apikey
Env var: GEMINI_API_KEY
"""
import os
import time
import random
from src.dispatchers.base import BaseDispatcher
from src.models import ModelResponse, Citation


# Retry on rate limits and overload (429/503)
RETRYABLE_PATTERNS = (
    "429", "resource_exhausted", "rate limit", "quota",
    "503", "unavailable", "overloaded",
)


def is_retryable(error: Exception) -> bool:
    msg = str(error).lower()
    return any(p in msg for p in RETRYABLE_PATTERNS)


class GeminiDispatcher(BaseDispatcher):
    name = "gemini"

    def __init__(self, config: dict):
        super().__init__(config)
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")
        self.client = genai.Client(api_key=api_key)
        self.max_retries = config.get("max_retries", 4)
        self.base_backoff = config.get("base_backoff_seconds", 8)
        self.enable_grounding = config.get("enable_grounding", False)

    def _build_config(self):
        """Build GenerateContentConfig with grounding tool if enabled.
        Returns None when grounding is off; passing None as config skips it."""
        if not self.enable_grounding:
            return None
        from google.genai import types
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        return types.GenerateContentConfig(tools=[grounding_tool])

    def _extract_citations(self, response) -> list[Citation]:
        """Pull citations from groundingMetadata.groundingChunks.
        Defensive against missing fields - older SDK versions and ungrounded
        responses won't have this structure."""
        citations = []
        try:
            candidate = response.candidates[0]
            metadata = getattr(candidate, "grounding_metadata", None)
            if not metadata:
                return citations
            chunks = getattr(metadata, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                if web:
                    citations.append(Citation(
                        url=getattr(web, "uri", "") or "",
                        title=getattr(web, "title", None),
                    ))
        except (AttributeError, IndexError):
            pass
        return citations

    def dispatch(self, client_id: str, prompt_id: str, prompt_text: str) -> ModelResponse:
        start = time.time()
        last_error = None
        gen_config = self._build_config()
        grounding_mode = "on" if self.enable_grounding else "off"

        for attempt in range(self.max_retries + 1):
            try:
                kwargs = {"model": self.model_id, "contents": prompt_text}
                if gen_config is not None:
                    kwargs["config"] = gen_config

                response = self.client.models.generate_content(**kwargs)
                latency_ms = int((time.time() - start) * 1000)
                response_text = response.text or ""
                citations = self._extract_citations(response) if self.enable_grounding else []

                # Pull search queries Gemini used (useful for debugging)
                search_queries = []
                try:
                    metadata = response.candidates[0].grounding_metadata
                    if metadata:
                        search_queries = list(getattr(metadata, "web_search_queries", []) or [])
                except (AttributeError, IndexError):
                    pass

                return ModelResponse(
                    client_id=client_id,
                    prompt_id=prompt_id,
                    prompt_text=prompt_text,
                    model_name=self.name,
                    model_id=self.model_id,
                    response_text=response_text,
                    citations=citations,
                    latency_ms=latency_ms,
                    grounding_mode=grounding_mode,
                    raw_payload={
                        "text": response_text,
                        "attempts": attempt + 1,
                        "grounded": self.enable_grounding,
                        "citation_count": len(citations),
                        "search_queries": search_queries,
                    },
                )

            except Exception as e:
                last_error = e
                if not is_retryable(e) or attempt == self.max_retries:
                    break
                wait = self.base_backoff * (2 ** attempt) + random.uniform(0, 2)
                print(f"    [gemini retry {attempt + 1}/{self.max_retries}] "
                      f"rate limited, waiting {wait:.1f}s...")
                time.sleep(wait)

        return ModelResponse(
            client_id=client_id,
            prompt_id=prompt_id,
            prompt_text=prompt_text,
            model_name=self.name,
            model_id=self.model_id,
            response_text="",
            latency_ms=int((time.time() - start) * 1000),
            grounding_mode=grounding_mode,
            error=str(last_error),
        )