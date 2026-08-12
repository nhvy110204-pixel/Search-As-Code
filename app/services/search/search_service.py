import logging
from typing import List, Dict, Any
from app.core.logger import service_boundary
from app.config.settings import settings
from app.models.user import User
from app.schemas.dto.search import (
    SearchRequest,
    SearchResponse,
    ChunkResultDTO,
    SearchAggregationsDTO,
    FacetGroupDTO,
    FacetBucketDTO
)

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, uow_factory):
        self.uow_factory = uow_factory

    @service_boundary("Search Knowledge")
    def search_knowledge(
        self,
        payload: SearchRequest,
        current_user: User
    ) -> SearchResponse:
        """
        Dịch vụ tra cứu danh sách Knowledge và tạo dữ liệu phân loại (Aggregations) cho Frontend.
        """
        with self.uow_factory() as uow:
            docs = uow.documents.get_active_documents(limit=payload.limit)
            
            results: List[ChunkResultDTO] = []
            doc_type_counts: Dict[str, int] = {}
            
            for doc in docs:
                if getattr(doc, "is_deleted", False):
                    continue
                
                ext = doc.file_name.split(".")[-1].lower() if "." in doc.file_name else "txt"
                doc_type_counts[ext] = doc_type_counts.get(ext, 0) + 1
                
                owner_display = current_user.email.split("@")[0] if current_user.email else "User"
                
                text_chunks = []
                if doc.markdown_content and len(doc.markdown_content.strip()) > 50 and not doc.markdown_content.startswith("# " + doc.file_name + "\n\n[Error"):
                    paragraphs = [p.strip() for p in doc.markdown_content.split("\n\n") if len(p.strip()) > 20]
                    if paragraphs:
                        text_chunks = paragraphs
                
                if not text_chunks:
                    count = doc.chunk_count if doc.chunk_count and doc.chunk_count > 0 else 1
                    text_chunks = [doc.description or doc.file_name] * count
                
                for i, chunk_text in enumerate(text_chunks):
                    results.append(
                        ChunkResultDTO(
                            filename=doc.file_name,
                            mimetype=doc.mime_type or "text/plain",
                            page=i + 1,
                            text=chunk_text,
                            score=1.0,
                            source_url=doc.file_name,
                            owner=str(doc.user_id),
                            owner_name=owner_display,
                            owner_email=current_user.email,
                            file_size=doc.file_size_bytes or 0,
                            connector_type="local",
                            embedding_model=settings.EMBEDDING_MODEL_NAME,
                            embedding_dimensions=settings.EMBEDDING_DIMENSION,
                            index=i
                        )
                    )

            type_buckets = [FacetBucketDTO(key=ext, count=cnt) for ext, cnt in doc_type_counts.items()]
            aggregations = SearchAggregationsDTO(
                data_sources=FacetGroupDTO(buckets=[FacetBucketDTO(key="local", count=len(results))]),
                document_types=FacetGroupDTO(buckets=type_buckets),
                owners=FacetGroupDTO(buckets=[FacetBucketDTO(key=current_user.email or "User", count=len(results))]),
                connector_types=FacetGroupDTO(buckets=[FacetBucketDTO(key="local", count=len(results))])
            )

            return SearchResponse(
                results=results[:payload.limit],
                aggregations=aggregations
            )
