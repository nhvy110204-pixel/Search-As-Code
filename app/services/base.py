from typing import Generic, List, Optional, Type, TypeVar, Any
from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.base import BaseRepository

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType")
UpdateSchemaType = TypeVar("UpdateSchemaType")
RepositoryType = TypeVar("RepositoryType", bound=BaseRepository)


class BaseService(
    Generic[ModelType, CreateSchemaType, UpdateSchemaType, RepositoryType]
):

    def __init__(
        self,
        db: Session,
        model: Type[ModelType],
        repository_class: Type[RepositoryType],
    ):
        self.db = db
        self.repository: RepositoryType = repository_class(model=model, db=db)

    def get(self, id: UUID) -> Optional[ModelType]:
        return self.repository.get(id)

    def get_multi(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[dict[str, Any]] = None,
        order_by: Optional[list[str]] = None
    ) -> List[ModelType]:
        return self.repository.get_multi(
            skip=skip, limit=limit, filters=filters, order_by=order_by
        )

    def create(self, *, payload: CreateSchemaType) -> ModelType:
        return self.repository.create(obj_in=payload)

    def update(self, *, db_obj: ModelType, payload: UpdateSchemaType) -> ModelType:
        return self.repository.update(db_obj=db_obj, obj_in=payload)

    def delete(self, *, id: UUID) -> None:
        self.repository.delete(id=id)

    def count(self, filters: Optional[dict] = None) -> int:
        return self.repository.count(filters=filters)
