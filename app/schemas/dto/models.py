from pydantic import BaseModel
from typing import Optional, List

class ModelOption(BaseModel):
    value: str
    label: str
    default: Optional[bool] = None

class ModelsResponse(BaseModel):
    language_models: List[ModelOption]
    embedding_models: List[ModelOption]

class OpenAIModelsRequest(BaseModel):
    api_key: Optional[str] = None

class AnthropicModelsRequest(BaseModel):
    api_key: Optional[str] = None

class IBMModelsRequest(BaseModel):
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    project_id: Optional[str] = None
