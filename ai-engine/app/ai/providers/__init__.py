from app.core.config import settings
from app.ai.providers.mock import MockProvider
from app.ai.providers.openai import OpenAIProvider
from app.ai.providers.gemini import GeminiProvider

def get_provider():
    providers = {"mock": MockProvider, "openai": OpenAIProvider, "gemini": GeminiProvider}
    try:
        return providers[settings.llm_provider.lower()]()
    except KeyError as exc:
        raise ValueError("LLM_PROVIDER must be mock, openai, or gemini") from exc
