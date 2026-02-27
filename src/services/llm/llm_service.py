from abc import ABC, abstractmethod
from openai import AsyncOpenAI, APIError

from google import genai
from google.genai import types
import boto3
import json
import asyncio
import grpc
from src import constants
from src.config import settings
import logging

logger = logging.getLogger(__name__)


class LLMService(ABC):

    @abstractmethod
    async def process_text(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


class _OpenAICompatibleService(LLMService):

    def __init__(self):
        logger.info(constants.LOG_LLM_SERVICE_INIT.format(service_name=self.__class__.__name__))
        self.client: AsyncOpenAI = self._create_client()
        self.model: str = self._get_model_name()

    @abstractmethod
    def _create_client(self) -> AsyncOpenAI:
        raise NotImplementedError

    @abstractmethod
    def _get_model_name(self) -> str:
        raise NotImplementedError

    async def process_text(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                stream=False,
            )
            content = response.choices[0].message.content
            return content or ""
        except APIError as e:
            error_message = constants.LOG_LLM_API_CALL_FAILED.format(service_name=self.__class__.__name__, error=e)
            logger.error(error_message)
            raise RuntimeError(constants.ERROR_MESSAGE_LLM_API_ERROR) from e


class OpenAILLMService(_OpenAICompatibleService):

    def _create_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(api_key=settings.openai_api_key)

    def _get_model_name(self) -> str:
        return settings.llm.openai.model_name


class OllamaLLMService(_OpenAICompatibleService):

    def _create_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(base_url=settings.llm.ollama.base_url, api_key="ollama")

    def _get_model_name(self) -> str:
        return settings.llm.ollama.model_name


class GrokLLMService(_OpenAICompatibleService):

    def _create_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(base_url=settings.llm.grok.base_url, api_key=settings.grok_api_key)

    def _get_model_name(self) -> str:
        return settings.llm.grok.model_name


class GeminiLLMService(LLMService):

    def __init__(self):
        logger.info(constants.LOG_LLM_SERVICE_INIT.format(service_name=self.__class__.__name__))
        self.client = genai.Client(api_key=settings.google_api_key)
        self.model_name = settings.llm.gemini.model_name

    async def process_text(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(system_instruction=system_prompt)
            )
            return response.text
        except Exception as e:
            error_message = constants.LOG_LLM_API_CALL_FAILED.format(service_name=self.__class__.__name__, error=e)
            logger.error(error_message)
            raise RuntimeError(constants.ERROR_MESSAGE_LLM_API_ERROR) from e


class BedrockLLMService(LLMService):

    def __init__(self):
        logger.info(constants.LOG_LLM_SERVICE_INIT.format(service_name=self.__class__.__name__))
        self.model_id = settings.llm.bedrock.model_id
        self.anthropic_version = settings.llm.bedrock.anthropic_version
        self.max_tokens = settings.llm.bedrock.max_tokens
        self.temperature = settings.llm.bedrock.temperature
        self.client = boto3.client(
            service_name="bedrock-runtime",
            region_name=settings.llm.bedrock.region_name,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

    async def process_text(self, system_prompt: str, user_prompt: str) -> str:
        loop = asyncio.get_running_loop()
        try:
            body = json.dumps({
                "anthropic_version": self.anthropic_version,
                "max_tokens": self.max_tokens,
                "system": system_prompt,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}]
            })
            response = await loop.run_in_executor(
                None, lambda: self.client.invoke_model(body=body, modelId=self.model_id)
            )
            response_body = json.loads(response.get("body").read())
            return response_body.get("content")[0].get("text")
        except Exception as e:
            error_message = constants.LOG_LLM_API_CALL_FAILED.format(service_name=self.__class__.__name__, error=e)
            logger.error(error_message)
            raise RuntimeError(constants.ERROR_MESSAGE_LLM_API_ERROR) from e