import uuid
import logging
from typing import List
from sqlalchemy import select
from sqlalchemy.orm import Session
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

from app.core.qdrant import qdrant_manager
from app.config.settings import settings
from app.sdk.low_level.processing import embed
from app.models.user_memory import UserMemory
from app.shared.enums import MemoryType

logger = logging.getLogger(__name__)

class MemoryService:
    """
    Lớp dịch vụ để quản lý Bộ nhớ dài hạn ngữ nghĩa (LTM).
    Sử dụng Qdrant để tìm kiếm tương đồng vector và PostgreSQL để lưu trữ audit trail bền vững.
    """

    @staticmethod
    async def save_memory(
        db: Session,
        user_id: uuid.UUID,
        content: str,
        memory_type: MemoryType = MemoryType.FACT
    ) -> uuid.UUID:
        """
        Lưu một bộ nhớ dài hạn ngữ nghĩa.
        1. Tạo text embedding bằng nhà cung cấp SDK.
        2. Lưu vector và metadata payload vào Qdrant.
        3. Lưu bản ghi cơ sở dữ liệu trong PostgreSQL.
        """
        if not content or not content.strip():
            raise ValueError("Nội dung bộ nhớ không được để trống")

        # Tạo vector embedding
        embeddings = await embed([content])
        if not embeddings:
            raise ValueError("Không thể tạo embedding cho nội dung bộ nhớ")
        vector = embeddings[0]
        
        embedding_id = uuid.uuid4()
        
        # 1. Upsert vector vào collection bộ nhớ Qdrant
        payload = {
            "user_id": str(user_id),
            "memory_type": str(memory_type.value),
            "content": content
        }
        try:
            qdrant_manager.upsert_vector(
                collection_name=settings.QDRANT_COLLECTION_MEMORIES,
                embedding_id=embedding_id,
                vector=vector,
                payload=payload
            )
        except Exception as e:
            logger.error("Không thể upsert vector bộ nhớ vào Qdrant: %s", str(e))
            # Trong ứng dụng production, chúng ta ghi vào DB bất kể, nên ít nhất nó được lưu trong PostgreSQL
        
        # 2. Lưu vào Postgres
        user_memory = UserMemory(
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            embedding_id=embedding_id
        )
        db.add(user_memory)
        
        return embedding_id

    @staticmethod
    async def recall_memories(
        db: Session,
        user_id: uuid.UUID,
        query: str,
        limit: int = 3,
        score_threshold: float = 0.4
    ) -> List[str]:
        """
        Gợi nhớ các bộ nhớ dài hạn phù hợp cho người dùng dựa trên tương đồng ngữ nghĩa.
        Dự phòng vào truy vấn DB nếu Qdrant ngoại tuyến/thất bại để hỗ trợ kiểm thử đơn vị ngoại tuyến.
        """
        if not query or not query.strip():
            return []

        embeddings = await embed([query])
        if not embeddings:
            return []
        vector = embeddings[0]
        
        # Truy vấn Qdrant với metadata filter
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=str(user_id))
                )
            ]
        )
        
        try:
            results = qdrant_manager.client.search(
                collection_name=settings.QDRANT_COLLECTION_MEMORIES,
                query_vector=vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold
            )
            
            # Trả về nội dung được lưu trực tiếp trong vector payloads
            memories = []
            for hit in results:
                if hit.payload and "content" in hit.payload:
                    memories.append(hit.payload["content"])
            return memories
        except Exception as e:
            logger.warning("Tìm kiếm bộ nhớ Qdrant thất bại, dự phòng vào truy vấn db: %s", str(e))
            # Dự phòng: truy vấn metadata trực tiếp PostgreSQL nếu Qdrant thất bại hoặc ngoại tuyến
            stmt = select(UserMemory.content).where(UserMemory.user_id == user_id).limit(limit)
            return list(db.scalars(stmt).all())
