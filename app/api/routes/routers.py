from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

# Register sub-routers
from app.api.controllers.users import router as users_router

api_router.include_router(users_router)

__all__ = ["api_router"]