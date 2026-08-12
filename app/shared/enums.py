import enum

class MessageRole(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

class MessageStatus(str, enum.Enum):
    PENDING = "pending"      # Đang xử lý ở backend
    STREAMING = "streaming"  # Đang yield từng token qua SSE/Websocket ra client
    COMPLETED = "completed"  # Đã hoàn thành sinh tin nhắn trọn vẹn
    FAILED = "failed"        # Lỗi kết nối/OOM giữa chừng (Tin nhắn lỗi sẽ báo đỏ trên giao diện)

class ChatStreamStatus(str, enum.Enum):
    STARTED = "started"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    DISCONNECTED = "disconnected"

class DocumentStatus(str, enum.Enum):
    PENDING = "pending"          # Chờ xử lý parse văn bản
    PARSING = "parsing"          # Đang parse văn bản
    PARSED = "parsed"            # Đã parse xong sang markdown
    SUMMARIZING = "summarizing"  # Đang tóm tắt tài liệu
    CHUNKING = "chunking"        # Đang cắt nhỏ văn bản
    DEDUPED = "deduped"          # Đã dedup chunks
    ENRICHED = "enriched"        # Đã enrich chunks với context
    EMBEDDING = "embedding"      # Đang sinh embedding
    LINKED = "linked"            # Đã link chunks với document
    PROCESSING = "processing"    # Đang cắt nhỏ (Chunking) và sinh Embedding
    COMPLETED = "completed"      # Đã xử lý xong, sẵn sàng tra cứu RAG
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"  # Đã xử lý xong nhưng có một số chunk lỗi
    FAILED = "failed"            # Gặp sự cố phân tích file

class StepStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class IngestionTaskStatus(str, enum.Enum):
    PENDING = "pending"
    CHECKING_CACHE = "checking_cache"
    PARSING = "parsing"            # Phase 1: Converting to MD via Docling
    SUMMARIZING = "summarizing"    # Phase 2: Generating Global Summary via LLM
    CHUNKING = "chunking"          # Phase 3: Structural splitting
    ENRICHING = "enriching"        # Phase 4: Anthropic Context Injection
    EMBEDDING = "embedding"        # Phase 5: Generating Dense + Sparse vectors
    SAVING = "saving"              # Flushing records to DB & Qdrant
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ProjectStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class InputSourceType(str, enum.Enum):
    TEXT = "text"
    DOCUMENT = "document"
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    URL = "url"


class InputStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

class MemoryType(str, enum.Enum):
    FACT = "fact"               # Sự thật trích xuất được (VD: Khách hàng đang dùng Mac M3)
    SUMMARY = "summary"         # Tóm tắt của một Chat Session cũ đã đóng để lưu vết kiến thức
    PREFERENCE = "preference"   # Thói quen học máy tự động đúc rút từ hành vi người dùng

class StopReason(str, enum.Enum):
    # Success
    COMPLETED = "completed"

    # Input
    OUT_OF_SCOPE = "out_of_scope"
    INVALID_INPUT = "invalid_input"
    GIBBERISH = "gibberish"
    USER_CANCELLED = "user_cancelled"

    # Safety
    PROMPT_INJECTION = "prompt_injection"
    SAFETY_VIOLATION = "safety_violation"

    # Evidence
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EVIDENCE_QUALITY_LOW = "evidence_quality_low"
    LOW_CONFIDENCE = "low_confidence"

    # Agent Quality
    STAGNATED = "stagnated"
    SEARCH_PLAN_FAILED = "search_plan_failed"
    HALLUCINATION_DETECTED = "hallucination_detected"
    CITATION_VALIDATION_FAILED = "citation_validation_failed"

    # Resource Limits
    MAX_TURNS_REACHED = "max_turns_reached"
    BUDGET_EXCEEDED = "budget_exceeded"
    CONTEXT_LENGTH_EXCEEDED = "context_length_exceeded"
    TIMEOUT = "timeout"

    # Infrastructure
    RETRIEVAL_FAILURE = "retrieval_failure"
    REPEATED_TOOL_FAILURES = "repeated_tool_failures"
    INTERNAL_ERROR = "internal_error"
