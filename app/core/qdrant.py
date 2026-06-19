"""Qdrant vector database client wrapper."""

from typing import Optional, List
import uuid
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, Filter, VectorParams, PointStruct
from qdrant_client.models import PointIdsList
from app.config.settings import settings


class QdrantManager:

    _instance: Optional['QdrantManager'] = None
    _client: Optional[QdrantClient] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        pass

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY,
            )
            self._init_collections()
        return self._client
    
    def _init_collections(self):
        try:
            self._client.get_collection(settings.QDRANT_COLLECTION_CHUNKS)
        except Exception:
            self._client.create_collection(
                collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
            )
        
        try:
            self._client.get_collection(settings.QDRANT_COLLECTION_MEMORIES)
        except Exception:
            self._client.create_collection(
                collection_name=settings.QDRANT_COLLECTION_MEMORIES,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
            )
        
        # Khởi tạo collection cho Semantic Cache nếu chưa tồn tại
        try:
            self._client.get_collection(settings.QDRANT_COLLECTION_SEMANTIC_CACHE)
        except Exception:
            self._client.create_collection(
                collection_name=settings.QDRANT_COLLECTION_SEMANTIC_CACHE,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
            )
    
    def upsert_vector(
        self,
        collection_name: str,
        embedding_id: uuid.UUID,
        vector: List[float],
        payload: dict,
    ) -> None:
        point = PointStruct(
            id=str(embedding_id),
            vector=vector,
            payload=payload,
        )
        self.client.upsert(
            collection_name=collection_name,
            points=[point],
        )
    
    def search_vectors(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int = 10,
        score_threshold: float = 0.5,
    ) -> List[dict]:
        results = self.client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold,
        )
        return [
            {
                "embedding_id": uuid.UUID(hit.id),
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in results
        ]
    
    def delete_vector(self, collection_name: str, embedding_id: uuid.UUID) -> None:
        self.client.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=[str(embedding_id)]), # Sửa ở đây
        )
 
    def delete_vectors_by_filter(self, collection_name: str, filter_condition: Filter) -> None:
        self.client.delete(
            collection_name=collection_name,
            points_selector=filter_condition,
        )
    
    def get_client(self) -> QdrantClient:
        return self.client

qdrant_manager = QdrantManager()
