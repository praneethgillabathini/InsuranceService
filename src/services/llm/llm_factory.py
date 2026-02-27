from src.config import settings
from src.services.llm.llm_service import (
    LLMService,
    OpenAILLMService,
    OllamaLLMService,
    GeminiLLMService,
    GrokLLMService,
    BedrockLLMService,
)
from src import constants


def get_llm_service() -> LLMService:
    provider = settings.llm.provider
    if provider == constants.LLM_PROVIDER_OPENAI:
        return OpenAILLMService()
    elif provider == constants.LLM_PROVIDER_OLLAMA:
        return OllamaLLMService()
    elif provider == constants.LLM_PROVIDER_GEMINI:
        return GeminiLLMService()
    elif provider == constants.LLM_PROVIDER_GROK:
        return GrokLLMService()
    elif provider == constants.LLM_PROVIDER_BEDROCK:
        return BedrockLLMService()
    raise ValueError(f"Unknown LLM provider configured: {provider}")