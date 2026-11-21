from functools import lru_cache

from ..config import settings
from .base import AIProvider


@lru_cache
def get_provider() -> AIProvider:
    if settings.ai_provider == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider()
    if settings.ai_provider == "legalai":
        from .legalai import LegalAIProvider

        return LegalAIProvider()
    if settings.ai_provider == "openai":
        from .ollama import OpenAICompatProvider

        return OpenAICompatProvider()
    from .mock import MockProvider

    return MockProvider()
