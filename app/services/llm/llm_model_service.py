import httpx
from fastapi import HTTPException, status
from openai import OpenAI
from app.config.settings import settings
from app.schemas.dto.models import ModelOption, ModelsResponse

class ModelService:
    @staticmethod
    def get_openai_models(api_key: str | None = None) -> ModelsResponse:
        key = api_key or settings.OPENAI_API_KEY
        if not key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OpenAI API key not provided and not found in environment."
            )
        try:
            client = OpenAI(api_key=key, timeout=5.0)
            client.models.list()
        except Exception as exc:
            err_msg = str(exc).lower()
            is_auth_error = any(x in err_msg for x in ["invalid_api_key", "incorrect api key", "unauthorized", "401", "authentication"])
            
            if not is_auth_error:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"OpenAI API key validation timed out or encountered a network error ({exc}). Bypassing to avoid blocking the user.")
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid OpenAI API key. Error: {str(exc)}"
                )
        return ModelsResponse(
            language_models=[
                ModelOption(value="gpt-4o-mini", label="GPT-4o Mini (Default)", default=True),
                ModelOption(value="gpt-4o", label="GPT-4o"),
                ModelOption(value="gpt-3.5-turbo", label="GPT-3.5 Turbo")
            ],
            embedding_models=[
                ModelOption(value="text-embedding-3-small", label="Text Embedding 3 Small (Default)", default=True),
                ModelOption(value="text-embedding-3-large", label="Text Embedding 3 Large"),
                ModelOption(value="text-embedding-ada-002", label="Text Embedding Ada 002")
            ]
        )

    @staticmethod
    def get_anthropic_models(api_key: str | None = None) -> ModelsResponse:
        return ModelsResponse(
            language_models=[
                ModelOption(value="claude-3-5-sonnet-latest", label="Claude 3.5 Sonnet (Default)", default=True),
                ModelOption(value="claude-3-5-haiku-latest", label="Claude 3.5 Haiku"),
                ModelOption(value="claude-3-opus-latest", label="Claude 3 Opus")
            ],
            embedding_models=[]
        )

    @staticmethod
    def get_ollama_models(endpoint: str = "http://localhost:11434") -> ModelsResponse:
        try:
            res = httpx.get(f"{endpoint}/api/tags", timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                models = data.get("models", [])
                lang_models = []
                for m in models:
                    name = m.get("name")
                    lang_models.append(ModelOption(value=name, label=name))
                if not lang_models:
                    lang_models = [ModelOption(value="llama3", label="Llama 3", default=True)]
                return ModelsResponse(language_models=lang_models, embedding_models=[])
        except Exception:
            pass
        return ModelsResponse(
            language_models=[
                ModelOption(value="llama3", label="Llama 3 (Default)", default=True),
                ModelOption(value="mistral", label="Mistral"),
                ModelOption(value="phi3", label="Phi 3")
            ],
            embedding_models=[
                ModelOption(value="nomic-embed-text", label="Nomic Embed Text (Default)", default=True)
            ]
        )

    @staticmethod
    def get_ibm_models(endpoint: str | None = None, api_key: str | None = None, project_id: str | None = None) -> ModelsResponse:
        return ModelsResponse(
            language_models=[
                ModelOption(value="ibm/granite-13b-instruct-v2", label="Granite 13b Instruct", default=True),
                ModelOption(value="meta/llama-3-70b-instruct", label="Llama 3 70b Instruct")
            ],
            embedding_models=[
                ModelOption(value="ibm/granite-embedding-30m-english-multilingual", label="Granite Embedding 30m English Multilingual", default=True)
            ]
        )
