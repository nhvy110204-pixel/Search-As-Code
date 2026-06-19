import json
import logging
import uuid
import asyncio
from typing import Optional, Dict, Any
from blake3 import blake3
from qdrant_client.models import PointIdsList
from app.config.settings import settings
from app.core.qdrant import qdrant_manager
from app.services.core.redis_service import redis_cache_service
from app.rag.embeddings.manager import EmbeddingManager

logger = logging.getLogger(__name__)


class SemanticCacheManager:
    """Quản lý bộ nhớ đệm ngữ nghĩa (Semantic Cache) kết hợp giữa Qdrant và Redis."""

    def __init__(self):
        self.collection_name = settings.QDRANT_COLLECTION_SEMANTIC_CACHE
        self.threshold = settings.SEMANTIC_CACHE_THRESHOLD
        self.ttl = settings.SEMANTIC_CACHE_TTL

    async def get_or_lock(self, query: str) -> tuple[Optional[Dict[str, Any]], bool]:
        """
        Kiểm tra cache hoặc lấy khóa (lock) để tránh tình trạng tranh chấp cache (Cache Stampede).
        Trả về:
          - (cached_data, False): nếu trúng cache (Cache Hit), không cần gọi LLM.
          - (None, True): nếu trượt cache và giành được lock thành công (Cache Miss - Caller cần gọi LLM).
          - (None, False): nếu bị timeout khi chờ hoặc xảy ra lỗi (Fallback gọi LLM trực tiếp, không ghi cache).
        """
        try:
            # 1. Băm câu hỏi bằng blake3 để tạo key an toàn
            query_hash = blake3(query.encode("utf-8")).hexdigest()
            redis_key = f"semantic_cache:{query_hash}"
            lock_key = f"semantic_lock:{query_hash}"

            # 2. Tìm kiếm vector tương đồng trên Qdrant để lấy key của Redis tương ứng
            provider = EmbeddingManager.get_provider(async_mode=False)
            query_vector = provider.embed_text(query)

            results = qdrant_manager.search_vectors(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=1,
                score_threshold=self.threshold
            )

            matched_redis_key = None
            if results:
                matched_redis_key = results[0].get("payload", {}).get("redis_key")
                score = results[0].get("score", 0.0)
                logger.info(f"Qdrant tìm thấy vector tương đồng với độ khớp {score:.4f}, trỏ về Redis key: {matched_redis_key}")

            # Nếu tìm thấy vector tương đồng trên Qdrant
            if matched_redis_key:
                if redis_cache_service.redis:
                    # Chờ tối đa 15 giây nếu có tiến trình khác đang giữ lock để sinh cache (Cache Stampede Protection)
                    for _ in range(75):  # 75 * 0.2s = 15s
                        cached_data = redis_cache_service.redis.get(matched_redis_key)
                        if cached_data:
                            logger.info(f"Semantic Cache HIT (Đọc từ Redis): key={matched_redis_key}")
                            return json.loads(cached_data), False
                        
                        # Kiểm tra xem có lock nào tương ứng với key này đang hoạt động không
                        matched_hash = matched_redis_key.split(":")[-1]
                        matched_lock_key = f"semantic_lock:{matched_hash}"
                        if not redis_cache_service.redis.exists(matched_lock_key):
                            # Không có lock và không có cache -> lock bị giải phóng nhưng cache lỗi/không ghi
                            break
                        await asyncio.sleep(0.2)
                    
                    logger.warning(f"Hết thời gian chờ (timeout) hoặc không tìm thấy cache trên Redis cho key={matched_redis_key}")

            # 3. Kịch bản Cache Miss: Thử giành lock để gọi LLM và ghi cache
            if redis_cache_service.redis:
                # Thiết lập lock với TTL 45 giây để tránh deadlock
                lock_acquired = redis_cache_service.redis.set(lock_key, "1", ex=45, nx=True)
                if lock_acquired:
                    logger.info(f"Giành được lock ghi cache thành công: lock_key={lock_key} (Cache Miss)")
                    return None, True
                else:
                    # Nếu không giành được lock, tức là có request tương tự đang chạy LLM, tiến hành đợi
                    logger.info(f"Đang có tiến trình khác chạy cho câu hỏi tương tự, tiến hành chờ đợi...")
                    for _ in range(75):  # 15s
                        cached_data = redis_cache_service.redis.get(redis_key)
                        if cached_data:
                            logger.info(f"Semantic Cache HIT sau khi chờ đợi lock: key={redis_key}")
                            return json.loads(cached_data), False
                        if not redis_cache_service.redis.exists(lock_key):
                            # Lock đã giải phóng nhưng cache rỗng -> thoát ra chạy trực tiếp
                            break
                        await asyncio.sleep(0.2)

        except Exception as e:
            logger.error(f"Lỗi hệ thống khi kiểm tra Semantic Cache: {e}")

        # Fallback: Trả về None để gọi trực tiếp LLM mà không giữ lock
        return None, False

    def save_sync(self, query: str, content: str, prompt_tokens: int, completion_tokens: int, query_hash: str | None = None) -> None:
        """
        Lưu câu trả lời vào Semantic Cache đồng bộ (chạy trong worker Celery).
        """
        if not query_hash:
            query_hash = blake3(query.encode("utf-8")).hexdigest()

        redis_key = f"semantic_cache:{query_hash}"
        lock_key = f"semantic_lock:{query_hash}"

        try:
            # 1. Sinh vector embedding cho câu hỏi
            provider = EmbeddingManager.get_provider(async_mode=False)
            query_vector = provider.embed_text(query)

            # 2. Lưu câu trả lời chi tiết và siêu dữ liệu (token) vào Redis
            cache_payload = {
                "content": content,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "query": query
            }

            if redis_cache_service.redis:
                redis_cache_service.redis.setex(
                    redis_key,
                    self.ttl,
                    json.dumps(cache_payload)
                )

                # 3. Lưu Vector vào Qdrant để tìm kiếm tương đồng sau này
                qdrant_payload = {
                    "query": query,
                    "redis_key": redis_key
                }
                # Sử dụng query_hash (UUID-like) làm ID trong Qdrant
                # Vì Qdrant yêu cầu ID định dạng UUID, ta sẽ chuyển query_hash thành định dạng UUID
                # Định dạng hex 32 ký tự của blake3 có thể chuyển trực tiếp thành UUID
                qdrant_id = uuid.UUID(query_hash[:32])

                qdrant_manager.upsert_vector(
                    collection_name=self.collection_name,
                    embedding_id=qdrant_id,
                    vector=query_vector,
                    payload=qdrant_payload
                )
                logger.info(f"Lưu Semantic Cache thành công: Qdrant ID={qdrant_id}, Redis key={redis_key}")
        except Exception as e:
            logger.error(f"Lỗi khi thực hiện lưu Semantic Cache: {e}")
        finally:
            # Luôn giải phóng lock sau khi ghi xong
            self.release_lock(query_hash)

    def release_lock(self, query_hash: str) -> None:
        """
        Giải phóng khóa lock nhanh chóng của câu hỏi.
        """
        try:
            if redis_cache_service.redis:
                lock_key = f"semantic_lock:{query_hash}"
                redis_cache_service.redis.delete(lock_key)
                logger.info(f"Đã giải phóng lock thành công cho lock_key={lock_key}")
        except Exception as e:
            logger.error(f"Lỗi khi giải phóng lock cho query_hash={query_hash}: {e}")

    def cleanup_orphans(self) -> None:
        """
        Dọn dẹp các vector mồ côi trong Qdrant khi các khóa Redis tương ứng đã hết hạn.
        Tác vụ này chạy định kỳ thông qua Celery Beat.
        """
        try:
            if not redis_cache_service.redis:
                logger.warning("Không thể dọn dẹp Qdrant vì Redis không hoạt động.")
                return

            logger.info("Bắt đầu quét và dọn dẹp các vector mồ côi trên Qdrant...")
            client = qdrant_manager.client
            offset = None
            total_checked = 0
            total_deleted = 0

            while True:
                response = client.scroll(
                    collection_name=self.collection_name,
                    limit=100,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset
                )
                points, next_offset = response

                if not points:
                    break

                orphan_ids = []
                for point in points:
                    redis_key = point.payload.get("redis_key")
                    total_checked += 1
                    
                    if redis_key:
                        # Kiểm tra sự tồn tại của key trong Redis
                        if not redis_cache_service.redis.exists(redis_key):
                            orphan_ids.append(point.id)
                            logger.info(f"Phát hiện vector mồ côi: Qdrant ID={point.id}, Redis Key={redis_key}")

                if orphan_ids:
                    # Tiến hành xóa hàng loạt các vector mồ côi khỏi Qdrant
                    client.delete(
                        collection_name=self.collection_name,
                        points_selector=PointIdsList(points=[str(i) for i in orphan_ids])
                    )
                    total_deleted += len(orphan_ids)

                offset = next_offset
                if not offset:
                    break

            logger.info(f"Hoàn tất dọn dẹp: Đã kiểm tra {total_checked} vector, đã xóa {total_deleted} vector mồ côi.")
        except Exception as e:
            logger.error(f"Lỗi hệ thống khi dọn dẹp vector mồ côi: {e}")


semantic_cache = SemanticCacheManager()
