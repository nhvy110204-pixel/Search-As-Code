from fastapi import APIRouter
from app.api.controllers.users import router as users_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(users_router)

__all__ = ["api_router"]