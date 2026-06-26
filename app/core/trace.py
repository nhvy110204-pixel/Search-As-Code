import time
import uuid
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.span import Span

logger = logging.getLogger(__name__)


@contextmanager
def trace_span_isolated(
    trace_id: uuid.UUID,
    span_name: str,
    span_type: str,
    model_name: Optional[str] = None
):
    """
    Context Manager sử dụng Session riêng biệt để lưu log, không bị ảnh hưởng bởi Rollback của UOW chính
    
    This function creates and manages a Span using an isolated database session to ensure
    that span logging is not affected by transaction rollbacks in the main business logic.
    
    Args:
        trace_id: UUID of the parent trace
        span_name: Name of the span (e.g., "llm_call", "search_web_many")
        span_type: Type of the span (e.g., "llm", "tool", "chain", "agent")
        model_name: Optional model name (for LLM spans)
    
    Yields:
        dict: A dictionary to populate with span data (input, output, tokens, cost)
              Keys: input, output, prompt_tokens, completion_tokens, cost_usd
    """
    start_time = time.perf_counter()
    
    # Mở một db session độc lập chỉ cho span này
    log_db: Session = SessionLocal()
    span_id = None
    
    try:
        # Tạo Span ở trạng thái chạy
        db_span = Span(
            trace_id=trace_id,
            name=span_name,
            type=span_type,
            model=model_name,
            status="running",
            started_at=datetime.now(timezone.utc)
        )
        log_db.add(db_span)
        log_db.commit()  # Commit ngay lập tức để ghi nhận span đang chạy
        span_id = db_span.id
    except Exception as err:
        logger.error(f"Failed to initialize trace span: {err}")
    finally:
        log_db.close()
    
    # Tạo một đối tượng giả lập/dict để code nghiệp vụ bên ngoài gán input/output
    span_data = {
        "input": None,
        "output": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0.0
    }
    
    try:
        yield span_data  # Thực thi nghiệp vụ chính
        status = "success"
    except Exception as e:
        status = "error"
        span_data["output"] = {"error": str(e)}
        raise e  # Ném lỗi lên trên để UOW chính rollback dữ liệu nghiệp vụ
    finally:
        # Khi kết thúc, mở lại session độc lập để cập nhật kết quả cuối cùng của Span
        if span_id:
            log_db = SessionLocal()
            try:
                db_span = log_db.get(Span, span_id)
                if db_span:
                    db_span.status = status
                    db_span.input = span_data["input"]
                    db_span.output = span_data["output"]
                    db_span.prompt_tokens = span_data["prompt_tokens"]
                    db_span.completion_tokens = span_data["completion_tokens"]
                    db_span.total_tokens = span_data["prompt_tokens"] + span_data["completion_tokens"]
                    db_span.cost_usd = span_data["cost_usd"]
                    db_span.ended_at = datetime.now(timezone.utc)
                    db_span.duration_ms = int((time.perf_counter() - start_time) * 1000)
                    log_db.commit()
            except Exception as update_err:
                logger.error(f"Failed to finalize trace span: {update_err}")
            finally:
                log_db.close()
