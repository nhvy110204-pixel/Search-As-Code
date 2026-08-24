"""
Ingestion Pipeline Constants & Configuration Defaults.
"""

# Maximum acceptable ratio of failed chunks (5%) to qualify as PARTIALLY_AVAILABLE instead of FAILED_RETRYABLE
PARTIAL_FAILURE_MAX_RATIO: float = 0.05

# Default vector versioning tag for embedding fingerprints
DEFAULT_EMBEDDING_VERSION: str = "v1"

# Maximum timeout for individual provider calls (seconds)
DEFAULT_PROVIDER_TIMEOUT_SECONDS: float = 30.0

# Batch sizes for ingestion operations
DEFAULT_PARSE_BATCH_SIZE_BOOK: int = 40
DEFAULT_PARSE_BATCH_SIZE_SLIDE: int = 15
DEFAULT_EMBEDDING_BATCH_SIZE: int = 10
