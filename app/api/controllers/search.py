from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.models.user import User
from app.schemas.dto.search import SearchRequest, SearchResponse
from app.services.search.search_service import SearchService

router = APIRouter(prefix="/search", tags=["search"])


def get_search_service(db=Depends(get_db)):
    def uow_factory():
        return UnitOfWork(db)
    yield SearchService(uow_factory=uow_factory)


@router.post("", response_model=SearchResponse)
@router.post("/", response_model=SearchResponse)
def search_knowledge(
    payload: SearchRequest,
    current_user: User = Depends(get_current_user),
    service: SearchService = Depends(get_search_service)
):
    """
    Endpoint tra cứu danh sách Knowledge và bộ lọc phân loại cho Frontend.
    """
    try:
        return service.search_knowledge(payload, current_user)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )
