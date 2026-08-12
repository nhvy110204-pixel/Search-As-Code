from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime
from app.shared.enums import StepStatus

@dataclass
class StepState:
    """State for a single pipeline step."""
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    tries: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineState:
    """Complete pipeline state for checkpoint/resume functionality."""
    
    # Step states
    virus_scan: StepState = field(default_factory=StepState)
    parse: StepState = field(default_factory=StepState)
    summary: StepState = field(default_factory=StepState)
    chunk: StepState = field(default_factory=StepState)
    dedup: StepState = field(default_factory=StepState)
    enrich: StepState = field(default_factory=StepState)
    embed: StepState = field(default_factory=StepState)
    link: StepState = field(default_factory=StepState)
    finalize: StepState = field(default_factory=StepState)
    
    # Tracking data
    global_summary: Optional[str] = None
    chunk_hashes: List[str] = field(default_factory=list)
    new_chunk_ids: List[str] = field(default_factory=list)
    existing_chunk_ids: List[str] = field(default_factory=list)
    embedded_chunk_ids: List[str] = field(default_factory=list)
    failed_chunk_ids: List[str] = field(default_factory=list)
    
    # Step history for debugging
    step_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    version: str = "1.0"
    last_updated: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSONB storage."""
        def _sanitize(obj: Any) -> Any:
            from uuid import UUID
            if isinstance(obj, UUID):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.isoformat()
            if hasattr(obj, "value"):
                return obj.value
            if isinstance(obj, dict):
                return {str(k): _sanitize(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple, set)):
                return [_sanitize(item) for item in obj]
            return obj

        def step_to_dict(step: StepState) -> Dict[str, Any]:
            return {
                "status": step.status.value,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                "tries": step.tries,
                "error": step.error,
                "metadata": _sanitize(step.metadata),
            }
        
        return _sanitize({
            "virus_scan": step_to_dict(self.virus_scan),
            "parse": step_to_dict(self.parse),
            "summary": step_to_dict(self.summary),
            "chunk": step_to_dict(self.chunk),
            "dedup": step_to_dict(self.dedup),
            "enrich": step_to_dict(self.enrich),
            "embed": step_to_dict(self.embed),
            "link": step_to_dict(self.link),
            "finalize": step_to_dict(self.finalize),
            "global_summary": self.global_summary,
            "chunk_hashes": self.chunk_hashes,
            "new_chunk_ids": self.new_chunk_ids,
            "existing_chunk_ids": self.existing_chunk_ids,
            "embedded_chunk_ids": self.embedded_chunk_ids,
            "failed_chunk_ids": self.failed_chunk_ids,
            "step_history": self.step_history,
            "version": self.version,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        })
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineState":
        """Create from dictionary for JSONB storage."""
        def dict_to_step(step_data: Dict[str, Any]) -> StepState:
            return StepState(
                status=StepStatus(step_data.get("status", "pending")),
                started_at=datetime.fromisoformat(step_data["started_at"]) if step_data.get("started_at") else None,
                completed_at=datetime.fromisoformat(step_data["completed_at"]) if step_data.get("completed_at") else None,
                tries=step_data.get("tries", 0),
                error=step_data.get("error"),
                metadata=step_data.get("metadata", {}),
            )
        
        return cls(
            virus_scan=dict_to_step(data.get("virus_scan", {})),
            parse=dict_to_step(data.get("parse", {})),
            summary=dict_to_step(data.get("summary", {})),
            chunk=dict_to_step(data.get("chunk", {})),
            dedup=dict_to_step(data.get("dedup", {})),
            enrich=dict_to_step(data.get("enrich", {})),
            embed=dict_to_step(data.get("embed", {})),
            link=dict_to_step(data.get("link", {})),
            finalize=dict_to_step(data.get("finalize", {})),
            global_summary=data.get("global_summary"),
            chunk_hashes=data.get("chunk_hashes", []),
            new_chunk_ids=data.get("new_chunk_ids", []),
            existing_chunk_ids=data.get("existing_chunk_ids", []),
            embedded_chunk_ids=data.get("embedded_chunk_ids", []),
            failed_chunk_ids=data.get("failed_chunk_ids", []),
            step_history=data.get("step_history", []),
            version=data.get("version", "1.0"),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else None,
        )
    
    def mark_step_started(self, step_name: str) -> None:
        """Mark a step as started."""
        step = getattr(self, step_name)
        step.status = StepStatus.IN_PROGRESS
        step.started_at = datetime.utcnow()
        self.last_updated = datetime.utcnow()
        self.step_history.append({
            "step": step_name,
            "action": "started",
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    def mark_step_completed(self, step_name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Mark a step as completed."""
        step = getattr(self, step_name)
        step.status = StepStatus.DONE
        step.completed_at = datetime.utcnow()
        if metadata:
            step.metadata.update(metadata)
        self.last_updated = datetime.utcnow()
        self.step_history.append({
            "step": step_name,
            "action": "completed",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata,
        })
    
    def mark_step_failed(self, step_name: str, error: str) -> None:
        """Mark a step as failed."""
        step = getattr(self, step_name)
        step.status = StepStatus.FAILED
        step.error = error
        step.tries += 1
        self.last_updated = datetime.utcnow()
        self.step_history.append({
            "step": step_name,
            "action": "failed",
            "timestamp": datetime.utcnow().isoformat(),
            "error": error,
            "tries": step.tries,
        })
    
    def get_next_step(self) -> Optional[str]:
        """Get the next step to execute based on current state."""
        steps_order = ["virus_scan", "parse", "summary", "chunk", "dedup", "enrich", "embed", "link", "finalize"]
        for step_name in steps_order:
            step = getattr(self, step_name)
            if step.status in [StepStatus.PENDING, StepStatus.FAILED]:
                return step_name
        return None
    
    def can_resume_from(self, step_name: str) -> bool:
        """Check if pipeline can resume from a specific step."""
        steps_order = ["virus_scan", "parse", "summary", "chunk", "dedup", "enrich", "embed", "link", "finalize"]
        step_index = steps_order.index(step_name)
        
        # All previous steps must be DONE
        for i in range(step_index):
            prev_step = getattr(self, steps_order[i])
            if prev_step.status != StepStatus.DONE:
                return False
        
        return True
