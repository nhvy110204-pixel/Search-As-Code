from fastapi import APIRouter, Query
from typing import Optional
from app.schemas.dto.models import ModelsResponse, OpenAIModelsRequest, AnthropicModelsRequest, IBMModelsRequest
from app.services.core.models import ModelService

router = APIRouter(prefix="/models", tags=["Models"])

@router.post("/openai", response_model=ModelsResponse)
def get_openai_models(payload: OpenAIModelsRequest):
    return ModelService.get_openai_models(payload.api_key)

@router.post("/anthropic", response_model=ModelsResponse)
def get_anthropic_models(payload: AnthropicModelsRequest):
    return ModelService.get_anthropic_models(payload.api_key)

@router.get("/ollama", response_model=ModelsResponse)
def get_ollama_models(endpoint: Optional[str] = Query("http://localhost:11434")):
    return ModelService.get_ollama_models(endpoint)

@router.post("/ibm", response_model=ModelsResponse)
def get_ibm_models(payload: IBMModelsRequest):
    return ModelService.get_ibm_models(payload.endpoint, payload.api_key, payload.project_id)
