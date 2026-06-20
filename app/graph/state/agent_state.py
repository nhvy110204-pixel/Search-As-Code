from typing import TypedDict, Annotated, List, Optional, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
import operator
from dataclasses import dataclass
from app.shared.enums import StopReason

@dataclass
class ErrorInfo:
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    node_name: Optional[str] = None
    retry_count: int = 0

class TurnRecord(TypedDict):
    turn_number: int
    generated_code: str
    stdout: str
    stderr: str
    returncode: int
    sdk_calls: int
    state_files: List[str]   # các file được serialize ra filesystem
    action_summary: str      # tóm tắt 1 dòng về hành động (cho bộ nhớ làm việc)
    outcome_summary: str     # tóm tắt 1 dòng về kết quả (cho bộ nhớ làm việc)

class TurnSummary(TypedDict):
    """Tóm tắt ngắn gọn của một vòng — chỉ giữ hành động + kết quả cho bộ nhớ làm việc."""
    turn: int
    action: str
    outcome: str

class AgentState(TypedDict):
    # --- Ngữ cảnh nhiệm vụ ---
    task_id: str
    directive: str                          # Chỉ thị nhiệm vụ gốc
    user_id: Optional[str]                  # ID duy nhất của người dùng (để cô lập bộ nhớ)
    project_id: Optional[str]              # ID của dự án (để liệt kê tài liệu, lọc nguồn)
    domain_context: Optional[str]           # Kiến thức miền
    constraints: List[str]                  # Các ràng buộc nhiệm vụ

    # --- Lịch sử hội thoại ---
    messages: Annotated[List[BaseMessage], add_messages]

    # --- Trạng thái thực thi ---
    turns: Annotated[List[TurnRecord], operator.add]  # Chỉ thêm vào
    current_turn: int
    max_turns: int                          # Giới hạn cứng (mặc định: 10)

    # --- Trạng thái sandbox ---
    state_dir: str                          # Đường dẫn đến thư mục trạng thái filesystem
    state_files: List[str]                  # Các file trong state_dir

    # --- Bộ nhớ làm việc ---
    turn_summaries: List[TurnSummary]       # Các tóm tắt ngắn gọn từ EXECUTOR
    last_coverage_summary: Optional[str]    # Cập nhật OBSERVER (đầu ra sdk.summarize)
    last_error: Optional[str]               # EXECUTOR ghi khi returncode != 0

    # --- Dừng dựa trên điểm số ---
    coverage_score: float                   # verified_targets / total_targets (0.0–1.0)
    confidence_score: float                 # điểm tin cậy trung bình (0.0–1.0)
    evidence_count: int
    retrieval_score: float
    low_retrieval_counter: int
    stagnation_counter: int

    # --- Kết quả ---
    results: Optional[List[Any]]            # Kết quả cuối cùng
    final_answer: Optional[str]
    unverified_claims: Optional[List[str]]
    citation_retry_counter: int
    is_complete: bool
    stop_reason: Optional[StopReason]
    error_info: Optional[ErrorInfo]

    # --- Số liệu ---
    total_sdk_calls: int
    total_tokens: int
    cost_usd: float

    # --- Cờ điều khiển ---
    _pending_code: Optional[str]            # Truyền code từ REASONER sang EXECUTOR
