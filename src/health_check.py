import logging
import requests
import json
import boto3
import openai
from google import genai
from groq import Groq
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Callable, Dict, Any

from .config import settings
from . import constants

logger = logging.getLogger(__name__)


def _check_api_key(provider_name: str, api_key: str) -> bool:
    if not api_key or api_key == "not-set":
        logger.error(constants.LOG_HEALTH_API_KEY_MISSING.format(provider_name=provider_name))
        return False
    return True


def _check_openai() -> bool:
    logger.info(constants.LOG_HEALTH_CHECKING.format(provider="OpenAI"))
    if not _check_api_key("OpenAI", settings.openai_api_key):
        return False
    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)
        client.models.list()
        logger.info(constants.LOG_HEALTH_PROVIDER_OK.format(provider="OpenAI"))
        return True
    except openai.AuthenticationError:
        logger.error(constants.LOG_HEALTH_OPENAI_AUTH_FAILED)
        return False
    except Exception as e:
        logger.error(constants.LOG_HEALTH_PROVIDER_ERROR.format(provider="OpenAI", error=e))
        return False


def _check_ollama() -> bool:
    base_url = settings.llm.ollama.base_url
    logger.info(constants.LOG_HEALTH_CHECKING_OLLAMA.format(base_url=base_url))
    try:
        health_check_url = base_url.removesuffix("/v1")
        response = requests.get(health_check_url, timeout=5)
        response.raise_for_status()
        if "Ollama is running" in response.text:
            logger.info(constants.LOG_HEALTH_PROVIDER_OK.format(provider="Ollama"))
            return True
        else:
            logger.warning(constants.LOG_HEALTH_OLLAMA_UNEXPECTED.format(response=response.text))
            return False
    except requests.exceptions.RequestException:
        logger.error(constants.LOG_HEALTH_OLLAMA_CONNECT_FAILED.format(base_url=base_url))
        return False


def _check_gemini() -> bool:
    logger.info(constants.LOG_HEALTH_CHECKING.format(provider="Google Gemini"))
    if not _check_api_key("Google Gemini", settings.google_api_key):
        return False
    try:
        client = genai.Client(api_key=settings.google_api_key)
        next(client.models.list())
        logger.info(constants.LOG_HEALTH_PROVIDER_OK.format(provider="Google Gemini"))
        return True
    except Exception as e:
        logger.error(constants.LOG_HEALTH_PROVIDER_ERROR.format(provider="Google Gemini", error=e))
        logger.error(constants.LOG_HEALTH_GEMINI_KEY_HINT)
        return False


def _check_grok() -> bool:
    logger.info(constants.LOG_HEALTH_CHECKING.format(provider="Groq"))
    if not _check_api_key("Groq", settings.grok_api_key):
        return False
    try:
        client = Groq(api_key=settings.grok_api_key)
        client.models.list()
        logger.info(constants.LOG_HEALTH_PROVIDER_OK.format(provider="Groq"))
        return True
    except Exception as e:
        logger.error(constants.LOG_HEALTH_PROVIDER_ERROR.format(provider="Groq", error=e))
        return False


def _get_bedrock_health_payload(model_id: str) -> Dict[str, Any]:
    if "anthropic" in model_id:
        return {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 1, "messages": [{"role": "user", "content": "health"}]}
    if "amazon" in model_id:
        return {"inputText": "health", "textGenerationConfig": {"maxTokenCount": 1}}
    if "meta" in model_id:
        return {"prompt": "health", "max_gen_len": 1}
    if "cohere" in model_id:
        return {"prompt": "health", "max_tokens": 1}
    raise ValueError(constants.LOG_HEALTH_BEDROCK_UNSUPPORTED_MODEL.format(model_id=model_id))


def _check_bedrock() -> bool:
    logger.info(constants.LOG_HEALTH_CHECKING.format(provider="AWS Bedrock"))
    if (not settings.aws_access_key_id or settings.aws_access_key_id == "not-set") and \
       (not settings.aws_secret_access_key or settings.aws_secret_access_key == "not-set"):
        logger.info(constants.LOG_HEALTH_BEDROCK_ASSUMING_IAM)

    model_id = settings.llm.bedrock.model_id
    try:
        session = boto3.Session(
            aws_access_key_id=settings.aws_access_key_id if settings.aws_access_key_id != "not-set" else None,
            aws_secret_access_key=settings.aws_secret_access_key if settings.aws_secret_access_key != "not-set" else None,
            region_name=settings.llm.bedrock.region_name
        )
        bedrock_runtime_client = session.client('bedrock-runtime')
        payload = _get_bedrock_health_payload(model_id)
        body = json.dumps(payload)
        bedrock_runtime_client.invoke_model(body=body, modelId=model_id, contentType='application/json', accept='application/json')
        logger.info(constants.LOG_HEALTH_BEDROCK_OK.format(model_id=model_id))
        return True
    except NoCredentialsError:
        logger.error(constants.LOG_HEALTH_BEDROCK_NO_CREDENTIALS)
        return False
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code == 'AccessDeniedException':
            logger.error(constants.LOG_HEALTH_BEDROCK_ACCESS_DENIED.format(model_id=model_id))
        elif error_code in ['ResourceNotFoundException', 'ValidationException']:
            logger.error(constants.LOG_HEALTH_BEDROCK_MODEL_NOT_FOUND.format(model_id=model_id, region=settings.llm.bedrock.region_name))
        else:
            logger.error(constants.LOG_HEALTH_BEDROCK_CLIENT_ERROR.format(error=e))
        return False
    except Exception as e:
        if isinstance(e, ValueError):
            logger.error(str(e))
            return False
        logger.error(constants.LOG_HEALTH_BEDROCK_UNEXPECTED_ERROR.format(error=e))
        return False


_HEALTH_CHECKS: Dict[str, Callable[[], bool]] = {
    "openai": _check_openai, "ollama": _check_ollama, "gemini": _check_gemini,
    "grok": _check_grok, "bedrock": _check_bedrock,
}


def check_llm_health() -> bool:
    provider = settings.llm.provider
    logger.info(constants.LOG_LLM_HEALTH_CHECK_START.format(provider=provider))
    check_function = _HEALTH_CHECKS.get(provider)
    if not (check_function and check_function()):
        logger.error(constants.LOG_LLM_HEALTH_CHECK_FAILED.format(provider=provider))
        return False
    logger.info(constants.LOG_LLM_HEALTH_CHECK_PASSED.format(provider=provider))
    return True