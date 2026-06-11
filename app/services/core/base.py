from typing import Generic, List, Optional, TypeVar, Any, Dict
from uuid import UUID
from pydantic import BaseModel

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class BaseService(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, repository):
        self.repo = repository

    def get(self, id: UUID, include_deleted: bool = False, options: List = None) -> Optional[ModelType]:
        return self.repo.get(id=id, include_deleted=include_deleted, options=options)

    def get_multi(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict] = None,
        order_by: Optional[List[str]] = None,
        options: Optional[List] = None,
        include_deleted: bool = False,
    ) -> List[ModelType]:
        return self.repo.get_multi(
            skip=skip,
            limit=limit,
            filters=filters,
            order_by=order_by,
            options=options,
            include_deleted=include_deleted,
        )

    def create(self, obj_in: CreateSchemaType) -> ModelType:
        return self.repo.create(obj_in)

    def update(self, id: UUID, obj_in: UpdateSchemaType | Dict[str, Any]) -> Optional[ModelType]:
        db_obj = self.repo.get(id)
        if not db_obj:
            return None
        return self.repo.update(db_obj, obj_in)

    def delete(self, id: UUID, hard: bool = False) -> bool:
        if hard:
            return self.repo.hard_delete(id)
        return self.repo.soft_delete(id)

    def count(self, filters: Optional[Dict] = None, include_deleted: bool = False) -> int:
        return self.repo.count(filters=filters, include_deleted=include_deleted)

    def exists(self, filters: Dict[str, Any]) -> bool:
        return self.repo.exists(filters=filters)
