"""
Unified Application Exceptions & Provider Error Taxonomy.
Categorizes transient vs permanent failures for deterministic state machine routing.
"""
from typing import Optional


class RAGFlashException(Exception):
    """Base exception for all RAGFlash errors."""
    def __init__(self, message: str, is_retryable: bool = False, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable
        self.details = details or {}


class ProviderError(RAGFlashException):
    """Base exception for external provider errors (LLM, Embeddings, OCR, VectorDB)."""
    def __init__(self, message: str, provider_name: str = "unknown", is_retryable: bool = True, details: Optional[dict] = None):
        super().__init__(message, is_retryable=is_retryable, details=details)
        self.provider_name = provider_name


class ProviderRateLimitError(ProviderError):
    """HTTP 429 / Token or RPM rate limit exceeded (Retryable with backoff)."""
    def __init__(self, message: str, provider_name: str = "unknown", retry_after_seconds: Optional[float] = None):
        super().__init__(message, provider_name=provider_name, is_retryable=True, details={"retry_after": retry_after_seconds})
        self.retry_after_seconds = retry_after_seconds


class ProviderTimeoutError(ProviderError):
    """Network connection or execution timeout (Retryable)."""
    def __init__(self, message: str, provider_name: str = "unknown"):
        super().__init__(message, provider_name=provider_name, is_retryable=True)


class ProviderConnectionError(ProviderError):
    """Socket disconnect or service unreachable (Retryable)."""
    def __init__(self, message: str, provider_name: str = "unknown"):
        super().__init__(message, provider_name=provider_name, is_retryable=True)


class ProviderAuthError(ProviderError):
    """Invalid API key, expired token, or unauthorized access (Non-retryable / Permanent)."""
    def __init__(self, message: str, provider_name: str = "unknown"):
        super().__init__(message, provider_name=provider_name, is_retryable=False)


class ProviderInvalidInputError(ProviderError):
    """Malformed request payload or unsupported parameters (Non-retryable / Permanent)."""
    def __init__(self, message: str, provider_name: str = "unknown"):
        super().__init__(message, provider_name=provider_name, is_retryable=False)


# ---------------------------------------------------------
# Ingestion & Data Integrity Exceptions
# ---------------------------------------------------------

class ReconciliationError(RAGFlashException):
    """
    Raised by the Hard Reconciliation Gate when actual counts do not match
    expected invariant constraints (Missing vectors, orphaned links, etc.).
    """
    def __init__(self, message: str, report: Optional[dict] = None, is_retryable: bool = True):
        super().__init__(message, is_retryable=is_retryable, details=report or {})
        self.report = report or {}


class QuarantineException(RAGFlashException):
    """Raised when a document is quarantined due to malware or severe Quality Gate rejection."""
    def __init__(self, message: str, reason: str, quality_score: Optional[float] = None):
        super().__init__(message, is_retryable=False, details={"reason": reason, "quality_score": quality_score})
        self.reason = reason
        self.quality_score = quality_score
