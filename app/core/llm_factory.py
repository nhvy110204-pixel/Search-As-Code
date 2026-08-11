import logging
from typing import Optional, Union
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from app.config.settings import settings

logger = logging.getLogger(__name__)

def get_llm_client(
    config: Optional[Union[dict, RunnableConfig]] = None,
    model_name: Optional[str] = None,
    streaming: bool = True
) -> ChatOpenAI:
    """
    Factory to resolve the LLM client:
    1. User's personal API key (BYOK) if available.
    2. Shared LiteLLM Proxy as the default platform provider.
    """
    user_api_keys = {}
    if config:
        configurable = config.get("configurable", config)
        if isinstance(configurable, dict):
            user_api_keys = configurable.get("user_api_keys") or {}

    model = model_name or settings.CHAT_MODEL_NAME

    # 1. BYOK Path: User has configured their own key
    if "openai" in user_api_keys and user_api_keys["openai"]:
        logger.info(f"Using user personal API Key (BYOK) for model {model}")
        return ChatOpenAI(
            api_key=user_api_keys["openai"],
            model=model,
            temperature=0.0,
            streaming=streaming
        )

    # 2. Proxy Path (Default): Use platform LiteLLM Proxy
    logger.info(f"Using platform LiteLLM Proxy at {settings.LITELLM_PROXY_URL} for model {model}")
    return ChatOpenAI(
        api_key=settings.LITELLM_PROXY_KEY,
        base_url=settings.LITELLM_PROXY_URL,
        model=model,
        temperature=0.0,
        streaming=streaming
    )
