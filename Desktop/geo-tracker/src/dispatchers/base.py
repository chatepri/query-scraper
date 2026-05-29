"""
Abstract base for all model dispatchers.
Adding a new provider = subclass + implement dispatch().
"""
from abc import ABC, abstractmethod
from src.models import ModelResponse


class BaseDispatcher(ABC):
    name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        self.model_id = config["model_id"]
        self.timeout = config.get("timeout_seconds", 30)
        self.max_tokens = config.get("max_output_tokens", 2048)

    @abstractmethod
    def dispatch(self, client_id: str, prompt_id: str, prompt_text: str) -> ModelResponse:
        """Send a prompt to the model and return a normalized response."""
        pass
