from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SearchPayloadFilters(BaseModel):
    data_sources: Optional[List[str]] = None
    document_types: Optional[List[str]] = None
    owners: Optional[List[str]] = None
    connector_types: Optional[List[str]] = None


class SearchRequest(BaseModel):
    query: str = "*"
    limit: int = 100
    scoreThreshold: float = 0.0
    filters: Optional[SearchPayloadFilters] = None


class ChunkResultDTO(BaseModel):
    filename: str
    mimetype: str = "text/plain"
    page: int = 1
    text: str = ""
    score: float = 1.0
    source_url: Optional[str] = None
    owner: Optional[str] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    file_size: Optional[int] = 0
    connector_type: Optional[str] = "local"
    embedding_model: Optional[str] = None
    embedding_dimensions: Optional[int] = None
    index: Optional[int] = 0


class FacetBucketDTO(BaseModel):
    key: str
    count: int


class FacetGroupDTO(BaseModel):
    buckets: List[FacetBucketDTO] = []


class SearchAggregationsDTO(BaseModel):
    data_sources: Optional[FacetGroupDTO] = Field(default_factory=FacetGroupDTO)
    document_types: Optional[FacetGroupDTO] = Field(default_factory=FacetGroupDTO)
    owners: Optional[FacetGroupDTO] = Field(default_factory=FacetGroupDTO)
    connector_types: Optional[FacetGroupDTO] = Field(default_factory=FacetGroupDTO)


class SearchResponse(BaseModel):
    results: List[ChunkResultDTO] = []
    aggregations: SearchAggregationsDTO = Field(default_factory=SearchAggregationsDTO)
