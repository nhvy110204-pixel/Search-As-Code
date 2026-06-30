from uuid import UUID
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.services.rag.ingestion.ingestion_service import IngestionService
from app.api.dependencies.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/ingestion", tags=["ingestion"])
security = HTTPBearer()


@router.post("/upload")
async def upload_document(
    project_id: UUID = Form(...),
    file: UploadFile = File(...),
    description: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    try:
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        
        # Get MIME type from file
        mime_type = file.content_type or "application/octet-stream"
        
        # Create ingestion service
        uow_factory = UnitOfWork(db)
        ingestion_service = IngestionService(uow_factory)
        
        # Upload document
        result = ingestion_service.upload_document(
            user_id=current_user.id,
            project_id=project_id,
            file_name=file.filename,
            file_content=file_content,
            file_size=file_size,
            mime_type=mime_type,
            description=description
        )

        return {
            "success": True,
            "data": result.model_dump()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.get("/status/{task_id}")
def get_ingestion_status(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        uow_factory = UnitOfWork(db)
        ingestion_service = IngestionService(uow_factory)
        
        status = ingestion_service.get_ingestion_status(task_id)

        return {
            "success": True,
            "data": status.model_dump()
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")
