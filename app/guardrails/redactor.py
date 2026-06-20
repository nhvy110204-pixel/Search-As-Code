import re
from typing import Any, Union

# Regex patterns to detect sensitive data
SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9\-]{20,}", re.IGNORECASE), "sk-proj-...[REDACTED]"),
    (re.compile(r"pk-lf-[a-zA-Z0-9\-]{20,}", re.IGNORECASE), "pk-lf-...[REDACTED]"),
    (re.compile(r"sk-lf-[a-zA-Z0-9\-]{20,}", re.IGNORECASE), "sk-lf-...[REDACTED]"),
    (re.compile(r"bearer\s+[a-zA-Z0-9\-\._~\+\/]+=*", re.IGNORECASE), "Bearer ...[REDACTED]"),
]

DB_PASSWORD_PATTERN = re.compile(r"((?:postgresql|postgres|mysql|sqlite|redis|amqp|mongodb)(?:\+[^:]+)?://[^:]+:)([^@]+)(@)", re.IGNORECASE)

def redact_text(text: str) -> str:
    """Apply regex masks to sensitive credentials inside a raw string."""
    if not isinstance(text, str):
        return text
        
    # Mask database passwords in connection URLs
    text = DB_PASSWORD_PATTERN.sub(r"\1[REDACTED]\3", text)
    
    # Mask API keys
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
        
    return text

def redact_sensitive_data(data: Any) -> Any:
    """
    Recursively redact sensitive patterns (API keys, connection strings, etc.)
    from dictionary payloads, lists, or primitive types.
    """
    if isinstance(data, dict):
        return {k: redact_sensitive_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        return redact_text(data)
    else:
        return data

def truncate_source_snippets(text: str, max_chars: int = 1000) -> str:
    """Truncate text if it exceeds max_chars, appending a warning suffix."""
    if not isinstance(text, str):
        return text
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... [TRUNCATED - EXCEEDED {max_chars} CHARS LIMIT]"
