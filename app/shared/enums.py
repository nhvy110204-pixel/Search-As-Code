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

class DocumentStatus(str, enum.Enum):
    PENDING = "pending"          # Chờ xử lý parse văn bản
    PROCESSING = "processing"    # Đang cắt nhỏ (Chunking) và sinh Embedding
    COMPLETED = "completed"      # Đã xử lý xong, sẵn sàng tra cứu RAG
    FAILED = "failed"            # Gặp sự cố phân tích file

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class MemoryType(str, enum.Enum):
    FACT = "fact"               # Sự thật trích xuất được (VD: Khách hàng đang dùng Mac M3)
    SUMMARY = "summary"         # Tóm tắt của một Chat Session cũ đã đóng để lưu vết kiến thức
    PREFERENCE = "preference"   # Thói quen học máy tự động đúc rút từ hành vi người dùng
