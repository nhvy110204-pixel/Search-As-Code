from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class SearchHit(BaseModel):
    id: str = Field(description="Unique identifier (e.g., chunk UUID or web URL)")
    title: str = Field(default="", description="Title of the source document or web page")
    content: str = Field(description="Text snippet/content of the search result")
    url: Optional[str] = Field(default=None, description="URL or filepath reference")
    score: float = Field(default=1.0, description="Relevance score (e.g., Qdrant cosine similarity)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional extra metadata fields")

class ExtractionResult(BaseModel):
    matches: bool = Field(default=True, description="Indicates if extraction was successful")
    data: Dict[str, Any] = Field(default_factory=dict, description="Key-value pairs of extracted data")
    confidence: float = Field(default=1.0, description="LLM confidence score (0.0 to 1.0)")
    raw_response: str = Field(default="", description="Raw response text from the LLM")

class SearchQuery(BaseModel):
    query: str
    limit: int = 10
