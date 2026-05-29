"""
Normalized data models used across the pipeline.
Every dispatcher returns a ModelResponse; the judge produces ExtractedBusiness
records (one per business found in each response).

Dataclass field ordering rule: every field WITHOUT a default must come
before every field WITH a default.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Citation:
    """A single source URL the model cited."""
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None


@dataclass
class ModelResponse:
    """Normalized response from any model. All dispatchers return this shape."""
    client_id: str
    prompt_id: str
    prompt_text: str
    model_name: str
    model_id: str
    response_text: str

    citations: list[Citation] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    grounding_mode: Optional[str] = None
    raw_payload: Optional[dict] = None
    run_iteration: int = 1   # 1-indexed: 1st, 2nd, 3rd... repeat of this prompt

    def to_dict(self):
        return asdict(self)


@dataclass
class ExtractedBusiness:
    """A single business/organization the judge extracted from a response."""
    response_id: int
    name: str
    normalized_name: str

    entity_type: Optional[str] = None
    position: Optional[int] = None
    sentiment: Optional[str] = None
    context_snippet: Optional[str] = None
    confidence: Optional[float] = None