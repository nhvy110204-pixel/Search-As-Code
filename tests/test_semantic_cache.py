import uuid
import json
import asyncio
import pytest
from unittest.mock import MagicMock, patch
from blake3 import blake3
from app.services.chat.semantic_cache import SemanticCacheManager
from qdrant_client.models import PointIdsList
from app.core.qdrant import qdrant_manager

# Thiết lập Mock Redis cục bộ cho kiểm thử
class MockRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttls[key] = ttl
        return True

    def exists(self, key):
        return 1 if key in self.store else 0

    def delete(self, key):
        if key in self.store:
            del self.store[key]
            if key in self.ttls:
                del self.ttls[key]
            return 1
        return 0


# Giả lập cho Qdrant client
class MockQdrantClient:
    def __init__(self):
        self.collection_store = {}

    def upsert(self, collection_name, points):
        if collection_name not in self.collection_store:
            self.collection_store[collection_name] = []
        self.collection_store[collection_name].extend(points)

    def delete(self, collection_name, points_selector):
        # Giả lập xóa hàng loạt
        if collection_name in self.collection_store:
            ids_to_delete = points_selector.points
            self.collection_store[collection_name] = [
                p for p in self.collection_store[collection_name]
                if p.id not in ids_to_delete
            ]

    def scroll(self, collection_name, limit=100, with_payload=True, with_vectors=False, offset=None):
        points = self.collection_store.get(collection_name, [])
        return points, None


def test_semantic_cache_stampede_protection():
    """
    Kiểm nghiệm cơ chế chống Cache Stampede bằng lock của Semantic Cache.
    """
    # 1. Khởi tạo mock cho Redis và Qdrant
    mock_redis = MockRedis()
    mock_qdrant = MockQdrantClient()

    # Lưu lại client cũ để restore sau test
    old_client = qdrant_manager._client
    qdrant_manager._client = mock_qdrant

    try:
        with patch("app.services.core.redis_service.redis_cache_service.redis", mock_redis), \
             patch("app.core.qdrant.qdrant_manager.search_vectors", return_value=[]), \
             patch("app.core.qdrant.qdrant_manager.upsert_vector") as mock_upsert, \
             patch("app.rag.embeddings.manager.EmbeddingManager.get_provider") as mock_embed_provider:

            # Giả lập sinh embedding
            mock_provider = MagicMock()
            mock_provider.embed_text.return_value = [0.1] * 1536
            mock_embed_provider.return_value = mock_provider

            manager = SemanticCacheManager()
            query = "Học Python có khó không?"
            query_hash = blake3(query.encode("utf-8")).hexdigest()
            lock_key = f"semantic_lock:{query_hash}"
            redis_key = f"semantic_cache:{query_hash}"

            async def run_stampede_flow():
                # 2. Request thứ nhất gọi get_or_lock -> Trượt cache (Cache Miss) và giành được lock
                cached_data, lock_acquired = await manager.get_or_lock(query)
                assert cached_data is None
                assert lock_acquired is True
                assert mock_redis.exists(lock_key) == 1

                # 3. Request thứ hai gọi đồng thời get_or_lock cho cùng câu hỏi
                # Giả lập tiến trình thứ nhất lưu cache thành công sau 0.2s
                async def mock_first_request_success():
                    await asyncio.sleep(0.2)
                    # Giả lập Celery worker lưu cache đồng bộ và nhả lock
                    manager.save_sync(query, "Không khó, rất dễ học!", 10, 20, query_hash)

                # Chạy đồng thời request thứ 2 và quá trình hoàn tất của request thứ 1
                async def mock_second_request():
                    cached_data_2, lock_acquired_2 = await manager.get_or_lock(query)
                    return cached_data_2, lock_acquired_2

                results = await asyncio.gather(
                    mock_first_request_success(),
                    mock_second_request()
                )

                cached_data_2, lock_acquired_2 = results[1]

                # Kiểm tra request thứ 2 trúng cache (Cache Hit) sau khi đợi lock giải phóng
                assert cached_data_2 is not None
                assert cached_data_2["content"] == "Không khó, rất dễ học!"
                assert lock_acquired_2 is False
                assert mock_redis.exists(lock_key) == 0  # Lock đã được giải phóng

            asyncio.run(run_stampede_flow())
    finally:
        qdrant_manager._client = old_client


def test_semantic_cache_cleanup_orphans():
    """
    Kiểm nghiệm cơ chế dọn dẹp các vector mồ côi (orphans) hàng đêm.
    """
    mock_redis = MockRedis()
    mock_qdrant = MockQdrantClient()

    # Lưu lại client cũ để restore sau test
    old_client = qdrant_manager._client
    qdrant_manager._client = mock_qdrant

    try:
        with patch("app.services.core.redis_service.redis_cache_service.redis", mock_redis):
            manager = SemanticCacheManager()

            # Tạo 3 vector trong Qdrant
            # Vector 1: Trỏ tới khóa Redis còn hoạt động
            # Vector 2: Trỏ tới khóa Redis đã hết hạn (không tồn tại trong Redis)
            # Vector 3: Trỏ tới khóa Redis đã hết hạn (không tồn tại trong Redis)
            uuid_active = str(uuid.uuid4())
            uuid_orphan1 = str(uuid.uuid4())
            uuid_orphan2 = str(uuid.uuid4())

            # Ghi nhận khóa của Vector 1 hoạt động trên Redis
            mock_redis.set(f"semantic_cache:{uuid_active}", "Active Cache")

            # Mock PointStruct cho Qdrant scroll
            from qdrant_client.http.models import PointStruct
            point_active = PointStruct(id=uuid_active, vector=[0.1]*1536, payload={"redis_key": f"semantic_cache:{uuid_active}"})
            point_orphan1 = PointStruct(id=uuid_orphan1, vector=[0.1]*1536, payload={"redis_key": f"semantic_cache:{uuid_orphan1}"})
            point_orphan2 = PointStruct(id=uuid_orphan2, vector=[0.1]*1536, payload={"redis_key": f"semantic_cache:{uuid_orphan2}"})

            mock_qdrant.collection_store[manager.collection_name] = [
                point_active,
                point_orphan1,
                point_orphan2
            ]

            # Chạy tác vụ quét dọn mồ côi
            manager.cleanup_orphans()

            # Xác nhận chỉ có vector active còn lại, 2 vector mồ côi đã bị xóa
            remaining_points = mock_qdrant.collection_store[manager.collection_name]
            assert len(remaining_points) == 1
            assert remaining_points[0].id == uuid_active
    finally:
        qdrant_manager._client = old_client


@pytest.mark.anyio
async def test_semantic_cache_project_isolation():
    """
    Xác minh rằng hai dự án (project_id) khác nhau truy vấn cùng câu hỏi
    sẽ được lưu ở hai khóa Redis/Qdrant riêng biệt, không bị leak xuyên dự án.
    """
    mock_redis = MockRedis()
    mock_qdrant = MockQdrantClient()

    old_client = qdrant_manager._client
    qdrant_manager._client = mock_qdrant

    try:
        with patch("app.services.core.redis_service.redis_cache_service.redis", mock_redis), \
             patch("app.core.qdrant.qdrant_manager.search_vectors") as mock_search, \
             patch("app.rag.embeddings.manager.EmbeddingManager.get_provider") as mock_embed_provider:

            mock_provider = MagicMock()
            mock_provider.embed_text.return_value = [0.1] * 1536
            mock_embed_provider.return_value = mock_provider

            manager = SemanticCacheManager()
            query = "Cấu hình mạng VPN thế nào?"
            project_a = str(uuid.uuid4())
            project_b = str(uuid.uuid4())
            query_hash = blake3(query.encode("utf-8")).hexdigest()

            # 1. Project A cache miss, acquire lock
            mock_search.return_value = [] # Không tìm thấy vector tương đồng cho Project A
            cached_data_a, lock_a = await manager.get_or_lock(query, project_id=project_a)
            assert cached_data_a is None
            assert lock_a is True

            # Kiểm tra xem lock có chứa project_id của A
            lock_key_a = f"semantic_lock:{project_a}:{query_hash}"
            assert mock_redis.exists(lock_key_a) == 1

            # 2. Lưu cache cho Project A
            manager.save_sync(query, "Hướng dẫn VPN của dự án A", 10, 20, query_hash, project_id=project_a)
            assert mock_redis.exists(lock_key_a) == 0 # Đã nhả lock
            cache_key_a = f"semantic_cache:{project_a}:{query_hash}"
            assert mock_redis.exists(cache_key_a) == 1 # Đã lưu cache

            # 3. Project B truy vấn cùng câu hỏi đó
            # Giả lập search_vectors trả về rỗng vì Qdrant filter project_id=project_b ngăn cản trả về cache của A
            mock_search.return_value = []
            cached_data_b, lock_b = await manager.get_or_lock(query, project_id=project_b)
            
            # Project B phải bị cache miss và giành được lock mới của riêng nó
            assert cached_data_b is None
            assert lock_b is True
            lock_key_b = f"semantic_lock:{project_b}:{query_hash}"
            assert mock_redis.exists(lock_key_b) == 1

            # 4. Khi search_vectors cho Project A, nó trả về thông tin Qdrant trỏ tới cache của A
            mock_search.return_value = [{"payload": {"redis_key": cache_key_a}, "score": 0.99}]
            cached_data_a_hit, lock_a_hit = await manager.get_or_lock(query, project_id=project_a)
            assert cached_data_a_hit is not None
            assert cached_data_a_hit["content"] == "Hướng dẫn VPN của dự án A"
            assert lock_a_hit is False

    finally:
        qdrant_manager._client = old_client

