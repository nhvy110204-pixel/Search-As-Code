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
tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])

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


@router.post("/upload-batch")
async def upload_documents_batch(
    project_id: UUID = Form(...),
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Tải lên nhiều file tài liệu cùng lúc cho một Project.
    """
    try:
        uow_factory = UnitOfWork(db)
        ingestion_service = IngestionService(uow_factory)
        
        results = []
        for file in files:
            try:
                file_content = await file.read()
                file_size = len(file_content)
                mime_type = file.content_type or "application/octet-stream"
                
                res = ingestion_service.upload_document(
                    user_id=current_user.id,
                    project_id=project_id,
                    file_name=file.filename or "unknown",
                    file_content=file_content,
                    file_size=file_size,
                    mime_type=mime_type,
                )
                results.append({
                    "file_name": file.filename,
                    "success": True,
                    "data": res.model_dump()
                })
            except Exception as item_err:
                results.append({
                    "file_name": file.filename,
                    "success": False,
                    "error": str(item_err)
                })
                
        return {
            "success": True,
            "total": len(files),
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch upload failed: {str(e)}")


@router.get("/events")
async def stream_ingestion_events(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Server-Sent Events (SSE) stream for real-time Ingestion updates of a project.
    """
    try:
        from fastapi.responses import StreamingResponse
        uow_factory = UnitOfWork(db)
        ingestion_service = IngestionService(uow_factory)
        
        return StreamingResponse(
            ingestion_service.stream_project_ingestion_events(project_id, current_user.id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open event stream: {str(e)}")


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



@router.post("/cancel/{task_id}")
@router.post("/tasks/{task_id}/cancel")
@tasks_router.post("/{task_id}/cancel")
def cancel_ingestion_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        uow_factory = UnitOfWork(db)
        ingestion_service = IngestionService(uow_factory)
        ingestion_service.cancel_ingestion_task(task_id, current_user.id)
        return {
            "status": "cancelled",
            "task_id": str(task_id)
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel task: {str(e)}")


@router.post("/reindex/{document_id}")
def reindex_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Kích hoạt re-index lại 1 tài liệu trong pipeline Ingestion.
    """
    try:
        uow_factory = UnitOfWork(db)
        ingestion_service = IngestionService(uow_factory)
        res = ingestion_service.reindex_document(document_id, current_user.id)
        return {
            "success": True,
            "data": res.model_dump()
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reindex document: {str(e)}")


@router.post("/reindex-project/{project_id}")
def reindex_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Kích hoạt re-index lại toàn bộ tài liệu trong một Project.
    """
    try:
        uow_factory = UnitOfWork(db)
        ingestion_service = IngestionService(uow_factory)
        res = ingestion_service.reindex_project(project_id, current_user.id)
        return {
            "success": True,
            "data": res.model_dump()
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reindex project: {str(e)}")


@router.get("/stats/{project_id}")
def get_project_stats(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lấy thống kê chỉ số tri thức & vector của một Project.
    """
    try:
        uow_factory = UnitOfWork(db)
        ingestion_service = IngestionService(uow_factory)
        res = ingestion_service.get_project_stats(project_id)
        return {
            "success": True,
            "data": res.model_dump()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get project stats: {str(e)}")

