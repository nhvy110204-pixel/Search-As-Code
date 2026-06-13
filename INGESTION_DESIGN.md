# Document Ingestion Pipeline - Conversion Plan

## 1. Mục tiêu
File này chuyển từ một đề xuất sản phẩm sang một **plan thực thi** cho dự án hiện tại. Mục tiêu là chuẩn hóa luồng upload document / ingest document theo workflow mới, đồng thời chỉ ra các thay đổi code và schema cần thiết để dự án convert theo flow này.

## 2. Mục tiêu kiến trúc
Workflow mới phải đáp ứng các yêu cầu sau:
- API upload trả ngay cho client, không block quá trình xử lý nặng
- Dùng `blake3_hash` để dedup document trên toàn hệ thống
- S3 upload idempotent theo hash hoặc doc_id
- Enqueue Celery task chỉ 1 lần cho document mới
- Worker resume được từ checkpoint khi bị crash hoặc retry
- Chunk dedup race-safe giữa nhiều worker / many documents
- Hỗ trợ hybrid embedding: dense + sparse/BM25
- Lưu trạng thái chi tiết trong JSONB để frontend/pipeline có thể resume và debug

## 3. Workflow mới

### 3.1 Upload API (Tầng 1)
```
UPLOAD API
│
├─ file_hash = blake3(file_bytes)
├─ S3 upload (idempotent key = hash, overwrite-safe)
├─ INSERT document (status=PENDING) ON CONFLICT(file_hash) DO NOTHING
│   └─ nếu conflict → return existing document_id (không enqueue lại)
└─ enqueue Celery task(document_id, idempotency_key=document_id)
```

#### Nội dung chi tiết
- `file_hash`: dùng `blake3` vì nhanh, collision cực thấp, idempotent key rõ ràng.
- `S3 upload`: lưu object path theo hash hoặc `doc_id/markdown.md` để dễ resume.
- `ON CONFLICT(file_hash) DO NOTHING`: tránh double processing tài liệu trùng.
- Nếu document đã tồn tại: trả `document_id` cũ, không enqueue task.
- Nếu mới: tạo record document + `ingestion_tasks`, enqueue Celery task với `document_id`.

### 3.2 Worker pipeline (Tầng 2)
Worker chạy theo luồng sau và checkpoint vào `document.pipeline_state` JSONB:

```
WORKER (mỗi step ghi checkpoint vào document.pipeline_state JSONB)
│
├─ [CHECK] đọc pipeline_state, nếu step đã DONE → skip, resume từ step tiếp theo
│
├─ STEP: PARSE
│   ├─ if state.parse == DONE → load markdown_text từ S3/cache, skip
│   ├─ else: parse → ghi markdown_text vào S3 (key=doc_id/markdown.md)
│   ├─ update state.parse = DONE; status = PARSED (15%)
│   └─ on fail: retry với backoff (Celery max_retries=3, countdown=2^n)
│       └─ nếu vượt max_retries → status = FAILED_PARSE, push dead-letter queue,
│           alert, KHÔNG retry vô hạn
│
├─ STEP: SUMMARY + CHUNK (parallel, dùng group/chord của Celery)
│   ├─ chord([summarize.s(md), chunk.s(md)], callback=enrich_and_embed.s())
│   ├─ nếu 1 trong 2 fail → cả chord fail → retry riêng step đó
│   │   (không re-run step đã DONE nhờ checkpoint)
│   └─ ghi global_summary + raw_chunks vào state khi cả 2 xong (status=35%)
│
├─ STEP: CHUNK DEDUP + INSERT (atomic, race-safe)
│   ├─ for each chunk: chunk_hash = blake3(content)
│   ├─ INSERT INTO chunks (hash, content, ...) 
│   │     VALUES (...) ON CONFLICT (hash) DO NOTHING
│   │     RETURNING id, (xmax = 0) AS is_new
│   │   -- is_new=true → vừa insert (cần embed)
│   │   -- is_new=false (conflict) → đã tồn tại (skip_embedding)
│   ├─ Nếu 2 worker cùng insert chunk X đồng thời:
│   │   DB unique constraint + ON CONFLICT đảm bảo chỉ 1 thắng,
│   │   worker thua đọc lại row đã có → coi như existing, KHÔNG lỗi
│   ├─ batch_new_chunks = [chunks với is_new=true]
│   ├─ batch_existing_chunks = [chunks với is_new=false]
│   └─ status = DEDUPED (50%)
│
├─ STEP: ENRICH (chỉ batch_new_chunks)
│   ├─ inject title + global_summary vào content
│   ├─ ghi enriched_content vào chunks table (UPDATE by id)
│   └─ status = ENRICHED (65%)
│
├─ STEP: EMBEDDING + QDRANT (per-chunk granularity, không per-batch all-or-nothing)
│   ├─ for batch in chunks(batch_new_chunks, size=N):
│   │   ├─ try: dense = embed_batch(batch); sparse = bm25_batch(batch)
│   │   ├─ if batch fail toàn bộ:
│   │   │   └─ fallback: retry per-chunk trong batch đó (isolate lỗi 1 chunk
│   │   │       không kéo cả batch — vd 1 chunk quá dài → truncate & retry,
│   │   │       chunk vẫn lỗi → mark chunks.embed_status=FAILED, tiếp tục)
│   │   ├─ qdrant.upsert(dense+sparse, ids=batch_ids)
│   │   │   -- Qdrant upsert là idempotent theo id, an toàn khi retry
│   │   ├─ UPDATE chunks SET embed_status='DONE' WHERE id IN batch_ids
│   │   └─ append batch_ids vào state.embedded_chunk_ids (checkpoint)
│   ├─ nếu worker crash giữa loop → resume đọc state.embedded_chunk_ids,
│   │   chỉ xử lý phần chunks chưa nằm trong list này
│   └─ status = EMBEDDING (90%)
│
├─ STEP: LINK (cho TẤT CẢ chunks — cả new đã embed xong VÀ existing skip_embedding)
│   ├─ INSERT INTO document_chunk_links (document_id, chunk_id)
│   │     SELECT doc_id, id FROM chunks WHERE hash IN (...)
│   │     ON CONFLICT (document_id, chunk_id) DO NOTHING
│   ├─ chunks có embed_status=FAILED vẫn được LINK (không block document
│   │   hoàn thành), nhưng đánh dấu document.has_partial_failures=true
│   └─ status = LINKED (95%)
│
└─ STEP: FINALIZE
    ├─ if any chunk.embed_status == FAILED:
    │   document.status = COMPLETED_WITH_WARNINGS
    │   → enqueue background re-embed task riêng cho các chunk FAILED
    │     (không retry toàn document)
    └─ else: document.status = COMPLETED (100%)
```

## 4. Required schema changes

### 4.1 Document table
- `blake3_hash: str` unique trên project hoặc toàn hệ thống
- `status: DocumentStatus` với giá trị `pending`, `processing`, `completed`, `completed_with_warnings`, `failed`
- `markdown_path: Optional[str]` hoặc `file_path_markdown` lưu đường dẫn markdown trên S3
- `processing_metadata: JSONB` để lưu global_summary, document-level metadata
- `pipeline_state: JSONB` để checkpoint từng step và resume trực tiếp trên document
- `has_partial_failures: bool` để báo warn nếu một số chunk embed failed

### 4.2 IngestionTask table
- giữ `status`, `progress`, `error_message`, `started_at`, `completed_at`
- có thể mở rộng thêm `attempts`, `last_error_step`, `worker_id`

### 4.3 DocumentChunk table
- hiện đã có `chunk_hash`, `embedding_id`, `content`
- cần bổ sung:
  - `enriched_content: Optional[str]`
  - `embed_status: str` với `pending`, `done`, `failed`
  - `chunk_source: str` hoặc `origin` để phân biệt `auto` vs `existing`
- duy trì unique constraint trên `chunk_hash`

### 4.4 DocumentChunkLink table
- thêm bảng `document_chunk_links(document_id, chunk_id)`
- unique constraint `(document_id, chunk_id)`
- phục vụ share chunk giữa nhiều document, link existing chunks

### 4.5 Index / constraint
- add unique index: `documents(project_id, blake3_hash)`
- add unique index: `document_chunks(chunk_hash)`
- add index: `document_chunks(document_id)`
- add index: `document_chunk_links(document_id, chunk_id)`

## 5. Implementation plan

### Phase 1: Schema + repo support
1. Tạo migration cho `documents`:
   - `blake3_hash` unique
   - `pipeline_state` JSONB
   - `has_partial_failures` boolean
2. Tạo migration cho `document_chunks`:
   - `enriched_content` JSONB/text
   - `embed_status` text
   - unique `chunk_hash`
3. Tạo migration cho `document_chunk_links` và repo tương ứng
4. Sửa `DocumentRepository`:
   - `find_by_hash(file_hash, project_id)`
   - `upsert_document_by_hash(...)`
5. Sửa `DocumentChunkRepository`:
   - `find_by_chunk_hash(chunk_hash)`
   - `insert_chunk_if_not_exists(...)` với ON CONFLICT
6. Mở rộng `UnitOfWork`:
   - add `ingestion_tasks` repository
   - add `document_chunk_links` repository nếu cần

### Phase 2: Task + queue infrastructure
1. Thêm `app/tasks/celery_app.py`
2. Thêm `app/tasks/ingestion_tasks.py`
3. Cấu hình `app/config/settings.py` cho RabbitMQ + Redis
4. Cập nhật Docker/compose để chạy RabbitMQ + Redis + Celery worker
5. Đảm bảo Celery task có `max_retries=3`, `retry_backoff=True`, `retry_jitter=True`

### Phase 3: Ingestion service + pipeline
1. Tạo `app/rag/ingestion/ingestion_service.py`
   - entrypoint cho API, tạo document + ingestion_task, enqueue Celery task
2. Tạo `app/rag/ingestion/ingestion_pipeline.py`
   - core runner resume từ `document.pipeline_state`
   - update document status and pipeline_state mỗi step
3. Tạo handler modules:
   - `parse_handler.py`
   - `summary_handler.py`
   - `chunk_handler.py`
   - `dedup_handler.py` (insert ON CONFLICT)
   - `enrich_handler.py`
   - `embed_handler.py`
4. Đảm bảo `summary` và `chunk` có thể chạy song song bằng `group/chord`
5. Thiết kế `pipeline_state` schema gần nhất với:
   - `parse: {status, tries, markdown_path}`
   - `summary: {status, global_summary}`
   - `chunk: {status, chunk_hashes}`
   - `dedup: {status, new_chunk_ids, existing_chunk_ids}`
   - `embed: {status, embedded_chunk_ids, failed_chunk_ids}`
   - `link: {status}`
   - `finalize: {status}`

### Phase 4: API controller
1. Sửa hoặc thêm route `POST /api/v1/documents/upload`
2. Sửa lôgic `ON CONFLICT(file_hash) DO NOTHING` / return existing document
3. Thêm route `GET /api/v1/ingest/tasks/{task_id}` để poll progress

### Phase 5: Operational hardening
1. Retry/backoff cho parse, summary, embedding
2. Dead-letter / alert khi parse fail quá 3 lần
3. Cleanup `pipeline_state` và S3 cache file khi document hoàn thành
4. Document deletion đồng bộ xóa S3, Qdrant, DB, link table
5. Partial failure handling: nếu chunk embed fail, document vẫn có thể `COMPLETED_WITH_WARNINGS`

### Phase 6: Observability, cost and debug
1. Mỗi bước pipeline phải có observability:
   - `parse`, `summary`, `chunk`, `dedup`, `enrich`, `embed`, `link`, `finalize`
   - step duration và retry count
   - step status changes và error reasons
   - task id / document id / worker id
2. Prometheus + Grafana:
   - expose metrics qua `/metrics`
   - thêm metric riêng cho ingestion pipeline:
     * `ingestion_tasks_total{status}`
     * `ingestion_step_duration_seconds{step}`
     * `ingestion_step_retries_total{step}`
     * `ingestion_failed_chunks_total`
     * `ingestion_embedding_batch_size`
     * `ingestion_cost_usd_total`
     * `ingestion_document_size_bytes`
     * `ingestion_qdrant_upserts_total`
3. Cost tracking & debug:
   - track token usage: `prompt_tokens`, `completion_tokens`, `total_tokens`
   - track estimated cost per LLM call and embedding call
   - track failed chunk ids và partial failures
   - track Qdrant payload size và batch sizes
4. Tracing:
   - API upload tạo trace/span, inject trace context vào queue message
   - worker extract trace context, nối trace đến Celery task
   - mỗi step sử dụng `trace_task_span(...)` hoặc tương đương
   - attach attributes: `task.id`, `document.id`, `step`, `status`, `error`, `token_count`, `cost_usd`
5. Debug artifacts:
   - `document.pipeline_state` lưu chi tiết step và checkpoint
   - `pipeline_state.failed_chunk_ids`
   - `pipeline_state.step_history`
   - `ingestion_task.error_message`
   - nếu dùng span DB model, lưu thêm `Span` record cho mỗi LLM/tool call
6. Grafana dashboard nên tối thiểu có:
   - ingestion throughput, success/failure rate
   - latency per step
   - cost per document
   - retry count and failed chunk ratio
   - Qdrant write throughput và embed batch performance

## 7. Implementation checklist
1. Schema
   - [ ] migration `documents` thêm `blake3_hash`, `pipeline_state`, `has_partial_failures`
   - [ ] migration `document_chunks` thêm `enriched_content`, `embed_status`, unique `chunk_hash`
   - [ ] migration `document_chunk_links` với unique constraint `(document_id, chunk_id)`
   - [ ] migration `ingestion_tasks` mở rộng `attempts`, `last_error_step`, `worker_id`
2. Repositories + UoW
   - [ ] `DocumentRepository.find_by_hash` và `upsert_document_by_hash`
   - [ ] `DocumentChunkRepository.insert_chunk_if_not_exists`
   - [ ] `DocumentChunkLinkRepository` hoặc repo link table tương ứng
   - [ ] UoW expose `ingestion_tasks`, `document_chunk_links`
3. Queue infrastructure
   - [ ] cấu hình RabbitMQ/Redis trong `settings.py`
   - [ ] tạo `app/tasks/celery_app.py`
   - [ ] tạo `app/tasks/ingestion_tasks.py`
   - [ ] cấu hình Docker compose để chạy Celery worker
4. Ingestion pipeline
   - [ ] `app/rag/ingestion/ingestion_service.py`
   - [ ] `app/rag/ingestion/ingestion_pipeline.py`
   - [ ] step handlers: parse, summary, chunk, dedup, enrich, embed, link, finalize
   - [ ] checkpoint state schema đủ chi tiết để resume
5. API + routes
   - [ ] route `POST /api/v1/documents/upload`
   - [ ] route `GET /api/v1/ingest/tasks/{task_id}`
   - [ ] đảm bảo upload idempotent theo hash
6. Observability + tracing
   - [ ] mở rộng Prometheus metric cho ingestion steps
   - [ ] định nghĩa metric `ingestion_tasks_total`, `ingestion_step_duration_seconds`, `ingestion_cost_usd_total`
   - [ ] propagate trace context từ API vào Celery task
   - [ ] attach step-level attributes `task.id`, `document.id`, `status`, `cost_usd`
7. Operational readiness
   - [ ] retry/backoff với Celery max_retries 3
   - [ ] dead-letter handling / alert khi task fail
   - [ ] partial failure handling và re-embed failed chunks
   - [ ] cleanup S3 cache / pipeline checkpoints khi hoàn thành

## 8. Conversion map: hiện tại → mới

| Hiện tại | Mới cần có | Note |
|---|---|---|
| `app/models/document.py` | giữ, thêm fields `pipeline_state`, `has_partial_failures` | không cần đổi hoàn toàn
| `app/models/ingestion_task.py` | giữ | dùng làm progress display, không phải pipeline state chính
| `app/models/document_chunk.py` | giữ, thêm `enriched_content`, `embed_status` | nếu muốn share chunk thì cần `document_chunk_links`
| `app/core/unit_of_work.py` | thêm repo `ingestion_tasks`, `document_chunk_links` | hiện có pattern UoW tốt
| `app/rag/embeddings/service.py` | giữ, bổ sung sparse/BM25 | dùng cho phase embedding
| `app/core/qdrant.py` | giữ | chỉ cần mở rộng payload hybrid
| `app/services/core/base.py` | giữ | dùng chung CRUD
| `app/services/core/document.py` | bổ sung `find_by_hash`, `upsert` | cho upload API
| `app/services/rag/document_chunk_embedding.py` | dùng lại hoặc tách rõ batch embed | hiện có logic embed async hữu ích

## 9. Decision points

### 9.1 Có cần `document_chunk_links` không?
- Nếu muốn reuse chunk giữa nhiều document và đúng luồng dedup/link, **cần**.
- Nếu chỉ cần dedup trong cùng một document thì có thể giữ `document_id` trong chunk và skip linking.
- Với flow của bạn, tốt nhất nên tạo `document_chunk_links` để cho phép `existing skip_embedding` được liên kết lại.

### 9.2 Dùng `document.pipeline_state` hay `ingestion_task` để resume?
- `document.pipeline_state` phù hợp cho resume step-by-step và debug file-level state.
- `ingestion_task` phù hợp cho progress/status hiển thị.
- Tốt nhất: giữ cả hai, nhưng state nội bộ pipeline được lưu vào `document.pipeline_state`.

### 9.3 Chunk dedup: DB vs in-memory
- Bắt buộc phải dùng DB unique + `ON CONFLICT` để race-safe.
- Không dùng chỉ in-memory hoặc chỉ dùng `SELECT` trước rồi insert.
- `RETURNING (xmax = 0) AS is_new` là cách chuyên nghiệp để biết chunk có mới hay không.

## 10. Minimal MVP to converge

1. `POST /api/v1/documents/upload` trả ngay và queue task
2. parse -> save markdown -> update document/pipeline_state
3. summary + chunk -> save metadata
4. dedup insert chunks bằng ON CONFLICT
5. embed batch -> Qdrant upsert
6. finalize document.status

Khi MVP hoạt động, mở rộng thêm:
- resume from checkpoint
- partial failure handling
- `document_chunk_links`
- sparse/BM25 hybrid payload
- dead-letter queue

## 11. Kết luận

File này bây giờ là một plan để dự án convert theo workflow mới. Giữ lại các cấu trúc hiện có càng nhiều càng tốt, nhưng phải mở rộng schema và thêm Celery / pipeline state để đảm bảo luồng `upload → queue → worker resume → dedup → embed → link → finalize` hoạt động đúng.

### Modified API Controller — Push to RabbitMQ

```python
from fastapi import APIRouter, UploadFile, Depends
from uuid import UUID
import hashlib
from app.tasks.ingestion_tasks import ingest_document
from app.core.dependencies import get_uow

router = APIRouter(prefix="/api/v1/ingest", tags=["Ingestion"])

@router.post("/upload")
async def upload_document(
    file: UploadFile,
    project_id: UUID,
    user_id: UUID,
    uow = Depends(get_uow)
):
    """
    Tầng 1: Sync API layer.
    1. Hash check
    2. S3 upload
    3. DB record creation
    4. **Push Celery task to RabbitMQ** ← KEY DIFFERENCE
    5. Return immediately (< 100ms)
    """
    file_bytes = await file.read()
    file_hash = hashlib.blake3(file_bytes).hexdigest()
    
    async with uow:
        # Check duplicate
        existing_doc = await uow.documents.find_by_hash(file_hash, project_id)
        if existing_doc:
            return {
                "message": "Document already exists",
                "document_id": str(existing_doc.id),
                "cached": True,
            }
        
        # Upload to S3
        storage_path = await storage_service.save_file_bytes(file_bytes, file.filename)
        
        # Create DB records
        document = await uow.documents.create({
            "user_id": user_id,
            "project_id": project_id,
            "file_name": file.filename,
            "storage_path": storage_path,
            "file_size_bytes": len(file_bytes),
            "mime_type": file.content_type,
            "blake3_hash": file_hash,
            "status": "pending"
        })
        
        task = await uow.ingestion_tasks.create({
            "document_id": document.id,
            "project_id": project_id,
            "user_id": user_id,
            "status": TaskStatus.PENDING
        })
        
        await uow.commit()
        
        # **KEY: Push to RabbitMQ via Celery (non-blocking)**
        ingest_document.apply_async(
            args=(
                str(task.id),
                str(document.id),
                storage_path,
                str(project_id),
            ),
            queue="ingestion",
            priority=5,  # 0-9 priority (higher = more urgent)
        )
    
    return {
        "task_id": str(task.id),
        "document_id": str(document.id),
        "status": "pending",
        "message": "Document queued for processing"
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: UUID, uow = Depends(get_uow)):
    """
    Poll task progress — frontend calls this every 1–5 seconds.
    """
    async with uow:
        task = await uow.ingestion_tasks.get(task_id)
    
    if not task:
        return {"error": "Task not found"}, 404
    
    return {
        "task_id": str(task.id),
        "status": task.status,           # "parsing" | "embedding" | "completed"
        "progress": task.progress,       # 0.0 → 100.0
        "error_message": task.error_message if task.status == "failed" else None,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }
```

### IngestionPipeline Update — Track Progress

```python
# app/rag/ingestion/ingestion_pipeline.py

from datetime import datetime
from app.shared.enums import TaskStatus

class IngestionPipeline:
    async def execute_async(self, task_id: UUID, document_id: UUID, storage_path: str, project_id: UUID):
        async with self.uow_factory() as uow:
            task = await uow.ingestion_tasks.get(task_id)
            doc = await uow.documents.get(document_id)
            
            try:
                # Phase 1: Parsing (10% → 25%)
                await self._update_task(uow, task_id, TaskStatus.PARSING, 15.0, started_at=datetime.utcnow())
                markdown_text = await self.parse_handler.handle(storage_path)
                doc.markdown_path = await self.parse_handler.save_md_cache(markdown_text, doc.id)
                
                # Phase 2: Summarizing (25% → 40%)
                await self._update_task(uow, task_id, TaskStatus.SUMMARIZING, 35.0)
                global_context = await self.summary_handler.handle(markdown_text, doc.file_name)
                doc.processing_metadata = {"global_summary": global_context}
                
                # Phase 3: Chunking (40% → 60%)
                await self._update_task(uow, task_id, TaskStatus.CHUNKING, 50.0)
                raw_chunks = await self.chunk_handler.handle(markdown_text)
                
                # Phase 4: Enriching (60% → 75%)
                await self._update_task(uow, task_id, TaskStatus.ENRICHING, 70.0)
                enriched_chunks = await self.enrich_handler.handle(
                    raw_chunks=raw_chunks,
                    global_summary=global_context,
                    title=doc.file_name
                )
                
                # Phase 5: Embedding (75% → 100%)
                await self._update_task(uow, task_id, TaskStatus.EMBEDDING, 85.0)
                chunk_count = await self.embed_handler.handle(doc.id, enriched_chunks)
                
                # Finalize
                doc.status = "completed"
                doc.chunk_count = chunk_count
                await self._update_task(uow, task_id, TaskStatus.COMPLETED, 100.0, completed_at=datetime.utcnow())
                await uow.commit()
                
                return {"status": "completed", "chunk_count": chunk_count}
                
            except Exception as e:
                await uow.rollback()
                await self._update_task(uow, task_id, TaskStatus.FAILED, error_message=str(e))
                doc.status = "failed"
                await uow.commit()
                raise
    
    async def _update_task(self, uow, task_id: UUID, status: TaskStatus, progress: float, started_at=None, completed_at=None, error_message=None):
        """Helper to update task progress in DB."""
        update_dict = {
            "status": status.value,
            "progress": progress,
        }
        if started_at:
            update_dict["started_at"] = started_at
        if completed_at:
            update_dict["completed_at"] = completed_at
        if error_message:
            update_dict["error_message"] = error_message
        
        await uow.ingestion_tasks.update(task_id, **update_dict)
        await uow.commit()
```

### Docker Compose for RabbitMQ + Redis

```yaml
# docker-compose.yml

version: '3.8'

services:
  rabbitmq:
    image: rabbitmq:3.12-management-alpine
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
    ports:
      - "5672:5672"    # AMQP
      - "15672:15672"  # Management UI
    healthcheck:
      test: rabbitmq-diagnostics ping
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: redis-cli ping
      interval: 10s
      timeout: 5s
      retries: 5

  celery_worker:
    build: .
    command: celery -A app.tasks.celery_app worker --loglevel=info --queues=ingestion --concurrency=2
    environment:
      RABBITMQ_HOST: rabbitmq
      RABBITMQ_USER: guest
      RABBITMQ_PASS: guest
      REDIS_HOST: redis
      REDIS_PORT: 6379
      DATABASE_URL: postgresql://user:pass@postgres:5432/ragflash
    depends_on:
      rabbitmq:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./app:/app
```

### Run Celery Worker (Development)

```bash
# Terminal 1: Run FastAPI server
uvicorn app.main:app --reload

# Terminal 2: Run Celery worker
celery -A app.tasks.celery_app worker --loglevel=info --queues=ingestion

# Terminal 3 (optional): Monitor Celery
celery -A app.tasks.celery_app events
```

### Frontend Progress Polling Example

```javascript
// React hook for polling task status
const useTaskProgress = (taskId) => {
  const [status, setStatus] = useState("pending");
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const interval = setInterval(async () => {
      const res = await fetch(`/api/v1/ingest/tasks/${taskId}`);
      const data = await res.json();
      setStatus(data.status);
      setProgress(data.progress);
      
      if (data.status === "completed" || data.status === "failed") {
        clearInterval(interval);
      }
    }, 2000); // Poll every 2 seconds

    return () => clearInterval(interval);
  }, [taskId]);

  return { status, progress };
};
```

## 12. Operational Best Practices (Production Hardening)  
1. **Memory Ceiling Constraints during Parse:** For high-throughput servers, running heavy native processing tasks via `docling` can trigger extreme RAM allocation spikes. Enforce a ceiling cutoff (e.g., limit execution size or isolate file processing queues).  
2. **Atomic Ingestion Cleanup Loop:** When deleting a `Document` entity, execution blocks MUST ensure deterministic removal across three isolated topologies:  
   * File deletion over Object Storage (S3/MinIO paths).  
   * Relational sweep via database cascading (`ondelete="CASCADE"` across chunks and metadata rows).  
   * Core deletion requests mapped directly to Qdrant using strict metadata routing filters (`document_id == target_uuid`).  
3. **Graceful Failure State Audits:** When processing nodes hit standard run exceptions (timeout restrictions, rate-limited tokens from OpenAI/Anthropic), catch blocks must guarantee updating `IngestionTask.status` to `TaskStatus.FAILED` with explicit logging to the `error_message` schema field. This saves engineering time when reviewing runtime exceptions.  
```