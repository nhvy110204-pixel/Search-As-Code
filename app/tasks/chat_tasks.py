import logging
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.chat_tasks.save_semantic_cache")
def save_semantic_cache(
    query: str,
    content: str,
    prompt_tokens: int,
    completion_tokens: int,
    query_hash: str | None = None
) -> None:
    """
    Tác vụ chạy dưới nền (Celery worker) để lưu câu trả lời vào Semantic Cache.
    """
    logger.info(f"Bắt đầu tác vụ chạy nền lưu cache cho query_hash={query_hash}")
    try:
        from app.services.chat.semantic_cache import semantic_cache
        semantic_cache.save_sync(
            query=query,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            query_hash=query_hash
        )
    except Exception as e:
        logger.error(f"Lỗi xảy ra trong Celery task lưu semantic cache: {e}")


@celery_app.task(name="app.tasks.chat_tasks.cleanup_semantic_cache_orphans")
def cleanup_semantic_cache_orphans() -> None:
    """
    Tác vụ chạy định kỳ (Celery Beat) để quét dọn các vector mồ côi trên Qdrant.
    """
    logger.info("Bắt đầu tác vụ chạy nền quét dọn vector mồ côi hàng ngày...")
    try:
        from app.services.chat.semantic_cache import semantic_cache
        semantic_cache.cleanup_orphans()
    except Exception as e:
        logger.error(f"Lỗi xảy ra trong Celery task quét dọn vector mồ côi: {e}")
