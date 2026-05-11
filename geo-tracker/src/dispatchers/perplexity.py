"""
Perplexity dispatcher.
Perplexity has an OpenAI-compatible API and returns citations natively -
this is the killer feature for GEO since you can see which URLs the model
pulled from.
Install: pip install openai
Get API key: https://www.perplexity.ai/settings/api
Env var: PERPLEXITY_API_KEY
"""
import os
import time
from src.dispatchers.base import BaseDispatcher
from src.models import ModelResponse, Citation


class PerplexityDispatcher(BaseDispatcher):
    name = "perplexity"

    def __init__(self, config: dict):
        super().__init__(config)
        from openai import OpenAI
        api_key = os.getenv("PERPLEXITY_API_KEY")
        if not api_key:
            raise RuntimeError("PERPLEXITY_API_KEY not set in environment")
        # Perplexity uses OpenAI's SDK with a different base URL
        self.client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")

    def dispatch(self, client_id: str, prompt_id: str, prompt_text: str) -> ModelResponse:
        start = time.time()
        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=self.max_tokens,
                timeout=self.timeout,
            )
            latency_ms = int((time.time() - start) * 1000)

            response_text = response.choices[0].message.content or ""

            # Perplexity puts citation URLs on the response object directly
            # The exact attribute has been search_results / citations depending on
            # API version - we try both safely
            citations = []
            raw_citations = (
                getattr(response, "search_results", None)
                or getattr(response, "citations", None)
                or []
            )
            for c in raw_citations:
                if isinstance(c, str):
                    citations.append(Citation(url=c))
                elif isinstance(c, dict):
                    citations.append(Citation(
                        url=c.get("url", ""),
                        title=c.get("title"),
                        snippet=c.get("snippet"),
                    ))

            return ModelResponse(
                client_id=client_id,
                prompt_id=prompt_id,
                prompt_text=prompt_text,
                model_name=self.name,
                model_id=self.model_id,
                response_text=response_text,
                citations=citations,
                latency_ms=latency_ms,
                raw_payload={
                    "text": response_text,
                    "citation_count": len(citations),
                },
            )
        except Exception as e:
            return ModelResponse(
                client_id=client_id,
                prompt_id=prompt_id,
                prompt_text=prompt_text,
                model_name=self.name,
                model_id=self.model_id,
                response_text="",
                latency_ms=int((time.time() - start) * 1000),
                error=str(e),
            )
