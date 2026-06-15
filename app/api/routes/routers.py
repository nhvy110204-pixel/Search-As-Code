from fastapi import APIRouter
from app.api.controllers.users import router as users_router
from app.api.controllers.auth import router as auth_router
from app.api.controllers.project import router as project_router
from app.api.controllers.document import router as document_router
from app.api.controllers.document_chunk import router as document_chunk_router
from app.api.controllers.chat_session import router as chat_session_router
from app.api.controllers.chat_message import router as chat_message_router
from app.api.controllers.chat import router as chat_router
from app.api.controllers.ingestion import router as ingestion_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(project_router)
api_router.include_router(document_router)
api_router.include_router(document_chunk_router)
api_router.include_router(chat_session_router)
api_router.include_router(chat_message_router)
api_router.include_router(chat_router)
api_router.include_router(ingestion_router)

__all__ = ["api_router"]
