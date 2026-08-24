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
    """Business status of a Document from the perspective of User and Chat Agent."""
    PENDING = "pending"                          # Uploaded, awaiting queue scheduling
    PROCESSING = "processing"                    # Ingestion pipeline actively executing
    READY = "ready"                              # 100% indexed, verified by Reconciliation Gate
    COMPLETED = "completed"                      # Legacy alias for READY
    PARTIALLY_AVAILABLE = "partially_available"  # Available for search with minor chunk losses (< 5%)
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"  # Legacy alias for PARTIALLY_AVAILABLE
    FAILED = "failed"                            # Unparseable or unrecoverable processing error
    QUARANTINED = "quarantined"                  # Malware detected or severely rejected by Quality Gate

    # Intermediate step markers for UI progress tracking
    PARSING = "parsing"
    PARSED = "parsed"
    SUMMARIZING = "summarizing"
    CHUNKING = "chunking"
    DEDUPED = "deduped"
    ENRICHED = "enriched"
    EMBEDDING = "embedding"
    LINKED = "linked"


class StepStatus(str, enum.Enum):
    """Technical execution state of an individual pipeline handler step."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    PARTIAL_SUCCESS = "partial_success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IngestionTaskStatus(str, enum.Enum):
    """Operational state of the background Ingestion Task / Queue Worker."""
    PENDING = "pending"
    RUNNING = "running"
    CHECKING_CACHE = "checking_cache"
    PARSING = "parsing"            # Phase 1: Converting to MD via IParseProvider
    SUMMARIZING = "summarizing"    # Phase 2: Generating Global Summary via ISummarizerProvider
    CHUNKING = "chunking"          # Phase 3: Structural splitting & fingerprinting
    DEDUPING = "deduping"          # Phase 3.5: Blake3 Chunk Deduplication
    ENRICHING = "enriching"        # Phase 4: Context Injection
    EMBEDDING = "embedding"        # Phase 5: Generating Dense + Sparse vectors
    LINKING = "linking"            # Phase 6: Document Knowledge Graph Linking
    SAVING = "saving"              # Flushing records to DB & Qdrant
    COMPLETED = "completed"        # Task finished successfully
    PARTIAL_SUCCESS = "partial_success"  # Task finished with minor acceptable warnings
    FAILED_RETRYABLE = "failed_retryable"  # Transient failure (429, timeout), ready for auto-retry
    FAILED_PERMANENT = "failed_permanent"  # Non-recoverable failure (corrupt file, bad auth)
    FAILED = "failed"              # General failure
    CANCELLED = "cancelled"


class FailureType(str, enum.Enum):
    """Categorized failure handling directives for error classification."""
    RETRYABLE = "retryable"        # Transient network drops, rate limits, timeouts, DB lock contention
    PERMANENT = "permanent"        # Corrupted PDF, unsupported MIME, auth failure, zero valid text
    QUARANTINE = "quarantine"      # Malware signature, exploit attempt, rejected by Quality Gate

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
