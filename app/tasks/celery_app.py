from celery import Celery
from app.config.settings import settings

celery_app = Celery(
    "ragflash_backend",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.ingestion_tasks",
        "app.tasks.chat_tasks"  # Tách biệt tác vụ Chat và Cache
    ]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    task_routes={
        "app.tasks.ingestion_tasks.ingest_document": {"queue": settings.CELERY_INGESTION_QUEUE},
        "app.tasks.ingestion_tasks.reembed_failed_chunks": {"queue": settings.CELERY_INGESTION_QUEUE},
        "app.tasks.chat_tasks.save_semantic_cache": {"queue": settings.CELERY_INGESTION_QUEUE},
        "app.tasks.chat_tasks.cleanup_semantic_cache_orphans": {"queue": settings.CELERY_INGESTION_QUEUE},
    },
    
    # Định kỳ dọn dẹp vector mồ côi trên Qdrant hàng ngày (mỗi 24h)
    beat_schedule={
        "cleanup-semantic-cache-orphans": {
            "task": "app.tasks.chat_tasks.cleanup_semantic_cache_orphans",
            "schedule": 86400.0,  # 86400 giây = 24 giờ
        }
    },
    
    task_default_retry_delay=60,
    task_max_retries=3,
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    task_retry_jitter=True,
    
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
    
    result_expires=3600,
    result_backend_transport_options={
        "retry_policy": {
            "timeout": 5.0,
            "max_retries": 3,
        }
    },
    
    task_track_started=True,
    task_send_sent_event=True,
    
    task_default_queue=settings.CELERY_INGESTION_QUEUE,
    
    task_queues=[
        {
            "name": settings.CELERY_INGESTION_QUEUE,
            "routing_key": settings.CELERY_INGESTION_QUEUE,
        },
        {
            "name": f"{settings.CELERY_INGESTION_QUEUE}_dlq",
            "routing_key": f"{settings.CELERY_INGESTION_QUEUE}_dlq",
        },
    ],
    
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_eager=True,
)