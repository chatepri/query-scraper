"""
Claude (Anthropic) dispatcher using the official anthropic SDK.
Install: pip install anthropic
Get API key: https://console.anthropic.com/
Env var: ANTHROPIC_API_KEY

Note: the LLM judge ALSO uses Anthropic but instantiates its own client.
That's intentional — judge and query model should be configured independently
so we can swap query model without touching the judge, and vice versa.
"""
import os
import time
from src.dispatchers.base import BaseDispatcher
from src.models import ModelResponse, Citation


class ClaudeDispatcher(BaseDispatcher):
    name = "claude"

    def __init__(self, config: dict):
        super().__init__(config)
        from anthropic import Anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
        self.client = Anthropic(api_key=api_key)
        self.max_output_tokens = config.get("max_output_tokens", 2048)
        self.enable_web_search = config.get("enable_web_search", True)
        self.web_search_max_uses = config.get("web_search_max_uses", 5)
        self.timeout = config.get("timeout_seconds", 60)

    def dispatch(self, client_id: str, prompt_id: str, prompt_text: str) -> ModelResponse:
        start = time.time()
        try:
            # Build tools list conditionally — empty list means ungrounded run
            # (knowledge presence mode). Tool present means grounded (visibility mode).
            tools = []
            if self.enable_web_search:
                tools.append({
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": self.web_search_max_uses,
                })

            kwargs = {
                "model": self.model_id,
                "max_tokens": self.max_output_tokens,
                "messages": [{"role": "user", "content": prompt_text}],
            }
            if tools:
                kwargs["tools"] = tools

            response = self.client.messages.create(**kwargs)
            latency_ms = int((time.time() - start) * 1000)

            # Claude returns a list of content blocks. With web_search enabled,
            # we get a mix of: text blocks, web_search_tool_use blocks, and
            # web_search_tool_result blocks. We concatenate text and extract
            # citations from the text blocks' .citations attribute.
            response_text_parts = []
            citations = []
            for block in response.content:
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    response_text_parts.append(block.text)
                    # Each text block may carry .citations (list of citation objects)
                    block_citations = getattr(block, "citations", None) or []
                    for c in block_citations:
                        citations.append(Citation(
                            url=getattr(c, "url", None),
                            title=getattr(c, "title", None),
                            snippet=getattr(c, "cited_text", None),
                        ))
                # web_search_tool_use and web_search_tool_result blocks
                # are tool-call internals — we ignore them for the response text
                # but they're available in raw_payload below if needed.

            response_text = "\n".join(response_text_parts)

            return ModelResponse(
                client_id=client_id,
                prompt_id=prompt_id,
                prompt_text=prompt_text,
                model_name=self.name,
                model_id=self.model_id,
                response_text=response_text,
                citations=citations,
                latency_ms=latency_ms,
                raw_payload={"text": response_text, "num_content_blocks": len(response.content)},
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