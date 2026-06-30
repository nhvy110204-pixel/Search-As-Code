from fastapi import APIRouter
import logging
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/docling", tags=["docling"])


@router.get("/health")
async def check_docling_health():
    """Check docling service health"""
    try:
        converter = DocumentConverter()
        
        return {"status": "healthy"}
    except ImportError as e:
        logger.error(f"Docling import failed: {e}")
        return {"status": "unhealthy", "message": "Docling library not available"}
    except Exception as e:
        logger.error(f"Docling health check failed: {e}")
        return {"status": "unhealthy", "message": str(e)}
