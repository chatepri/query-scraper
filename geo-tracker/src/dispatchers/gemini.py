"""
Gemini dispatcher using google-genai SDK.
Install: pip install google-genai
Get API key: https://aistudio.google.com/apikey
Env var: GEMINI_API_KEY
"""
import os
import time
from src.dispatchers.base import BaseDispatcher
from src.models import ModelResponse, Citation


class GeminiDispatcher(BaseDispatcher):
    name = "gemini"

    def __init__(self, config: dict):
        super().__init__(config)
        # Lazy import so the module doesn't fail if the SDK isn't installed
        # until you actually try to use Gemini
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")
        self.client = genai.Client(api_key=api_key)

    def dispatch(self, client_id: str, prompt_id: str, prompt_text: str) -> ModelResponse:
        start = time.time()
        try:
            # Gemini doesn't return citations the way Perplexity does by default.
            # We can optionally enable Google Search grounding to get sources,
            # but it costs more. For v1, plain generation.
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt_text,
            )
            latency_ms = int((time.time() - start) * 1000)

            response_text = response.text or ""

            # If grounding is enabled later, citations would be extracted here
            # from response.candidates[0].grounding_metadata
            citations = []

            return ModelResponse(
                client_id=client_id,
                prompt_id=prompt_id,
                prompt_text=prompt_text,
                model_name=self.name,
                model_id=self.model_id,
                response_text=response_text,
                citations=citations,
                latency_ms=latency_ms,
                raw_payload={"text": response_text},
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
