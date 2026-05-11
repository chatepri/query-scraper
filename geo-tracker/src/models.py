"""
Normalized data models used across the pipeline.
Every dispatcher returns a ModelResponse; the parser produces Mentions.
Keeping these dataclasses small and explicit makes refactors painless.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Citation:
    """A single source URL the model cited (Perplexity returns these natively)."""
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None


@dataclass
class ModelResponse:
    """Normalized response from any model. All dispatchers return this shape."""
    client_id: str
    prompt_id: str
    prompt_text: str
    model_name: str            # "gemini", "perplexity", etc.
    model_id: str              # actual model string used in the API call
    response_text: str
    citations: list[Citation] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    raw_payload: Optional[dict] = None   # full API response for debugging

    def to_dict(self):
        d = asdict(self)
        return d


@dataclass
class Mention:
    """A single brand mention detected by the parser/judge."""
    response_id: int           # FK to runs table
    entity_name: str           # "YTEN" or competitor name
    entity_type: str           # "client" or "competitor"
    is_mentioned: bool
    position: Optional[int] = None      # 1 = first mentioned, 2 = second, etc.
    sentiment: Optional[str] = None     # "positive" | "neutral" | "negative"
    context_snippet: Optional[str] = None   # the surrounding text
    cited_url: Optional[str] = None     # if the mention came with a citation
    judge_confidence: Optional[float] = None  # 0.0 to 1.0
