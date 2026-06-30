from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class AgentSettings(BaseModel):
    llm_model: Optional[str] = None
    llm_provider: Optional[str] = None
    system_prompt: Optional[str] = None


class KnowledgeSettings(BaseModel):
    embedding_model: Optional[str] = None
    embedding_provider: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    table_structure: bool = False
    ocr: bool = False
    picture_descriptions: bool = False


class ProviderSettings(BaseModel):
    openai: Optional[dict[str, Any]] = None
    anthropic: Optional[dict[str, Any]] = None
    watsonx: Optional[dict[str, Any]] = None
    ollama: Optional[dict[str, Any]] = None


class OnboardingState(BaseModel):
    current_step: Optional[int] = None
    assistant_message: Optional[dict[str, Any]] = None
    selected_nudge: Optional[str] = None
    card_steps: Optional[dict[str, Any]] = None
    upload_steps: Optional[dict[str, Any]] = None
    openrag_docs_filter_id: Optional[str] = None
    user_doc_filter_id: Optional[str] = None


class IngestionDefaults(BaseModel):
    chunkSize: Optional[int] = None
    chunkOverlap: Optional[int] = None
    separator: Optional[str] = None
    embeddingModel: Optional[str] = None


class SettingsResponse(BaseModel):
    langflow_url: Optional[str] = None
    flow_id: Optional[str] = None
    ingest_flow_id: Optional[str] = None
    langflow_public_url: Optional[str] = None
    edited: bool = False
    onboarding: Optional[OnboardingState] = None
    providers: Optional[ProviderSettings] = None
    knowledge: Optional[KnowledgeSettings] = None
    agent: Optional[AgentSettings] = None
    langflow_edit_url: Optional[str] = None
    langflow_ingest_edit_url: Optional[str] = None
    ingestion_defaults: Optional[IngestionDefaults] = None
    localhost_url: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class SettingsUpdate(BaseModel):
    langflow_url: Optional[str] = None
    flow_id: Optional[str] = None
    ingest_flow_id: Optional[str] = None
    langflow_public_url: Optional[str] = None
    edited: Optional[bool] = None
    onboarding: Optional[OnboardingState] = None
    providers: Optional[ProviderSettings] = None
    knowledge: Optional[KnowledgeSettings] = None
    agent: Optional[AgentSettings] = None
    langflow_edit_url: Optional[str] = None
    langflow_ingest_edit_url: Optional[str] = None
    ingestion_defaults: Optional[IngestionDefaults] = None
    localhost_url: Optional[str] = None
