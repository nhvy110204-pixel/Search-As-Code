from pathlib import Path
from fastapi import HTTPException
from app.config.settings import settings

MAGIC_BYTES = {
    b'\x25\x50\x44\x46': 'application/pdf',  # PDF
    b'\x50\x4b\x03\x04': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # DOCX (ZIP)
    b'\xd0\xcf\x11\xe0': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # DOC (legacy)
    b'\x50\x4b\x05\x06': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # DOCX (empty ZIP)
}


def validate_file_size(file_size: int, max_size: int = None) -> None:
    if max_size is None:
        max_size = settings.MAX_FILE_SIZE_BYTES
    
    if file_size > max_size:
        max_size_mb = max_size / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds maximum allowed size of {max_size_mb:.0f}MB"
        )
    
    if file_size == 0:
        raise HTTPException(status_code=400, detail="File is empty")


def validate_file_type(
    file_bytes: bytes,
    filename: str,
    allowed_types: list[str] = None,
    allowed_extensions: list[str] = None
) -> None:
    if allowed_types is None:
        allowed_types = settings.ALLOWED_FILE_TYPES
    if allowed_extensions is None:
        allowed_extensions = settings.ALLOWED_FILE_EXTENSIONS
    
    file_ext = Path(filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=415,
            detail=f"File extension {file_ext} not allowed. Allowed: {', '.join(allowed_extensions)}"
        )
    
    if file_ext in ['.pdf', '.docx', '.doc']:
        detected_type = detect_file_type_from_bytes(file_bytes)
        
        if detected_type and detected_type not in allowed_types:
            raise HTTPException(
                status_code=415,
                detail=f"File content type {detected_type} does not match extension {file_ext}. File may be corrupted or renamed."
            )
        
        if file_ext == '.docx' and detected_type == 'application/zip':
            if not is_valid_docx(file_bytes):
                raise HTTPException(
                    status_code=415,
                    detail="File is not a valid DOCX file. It may be a regular ZIP file."
                )


def detect_file_type_from_bytes(file_bytes: bytes) -> str | None:
    if not file_bytes:
        return None
    
    for magic, mime_type in MAGIC_BYTES.items():
        if file_bytes.startswith(magic):
            return mime_type
    
    if file_bytes.startswith(b'\x50\x4b\x03\x04') or file_bytes.startswith(b'\x50\x4b\x05\x06'):
        return 'application/zip'
    
    try:
        file_bytes[:100].decode('utf-8')
        return 'text/plain'
    except UnicodeDecodeError:
        pass
    
    return None


def is_valid_docx(file_bytes: bytes) -> bool:
    try:
        content = file_bytes.decode('latin-1', errors='ignore')
        return '[Content_Types].xml' in content or 'word/' in content
    except Exception:
        return False
