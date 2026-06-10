from typing import Generic, List, Optional, Type, TypeVar, Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, delete, asc, desc
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class BaseRepository(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType], db: Session):
        self.model = model
        self.db = db

    def apply_filters(self, query, filters: Optional[dict]):
        if not filters:
            return query

        conditions = []
        for key, value in filters.items():
            if value is None:
                continue

            if "__" in key:
                field_name, op = key.split("__", 1)

                if not hasattr(self.model, field_name):
                    continue

                field = getattr(self.model, field_name)

                match op:
                    case "gte":
                        conditions.append(field >= value)
                    case "gt":
                        conditions.append(field > value)
                    case "lte":
                        conditions.append(field <= value)
                    case "lt":
                        conditions.append(field < value)
                    case "like":
                        conditions.append(field.like(value))
                    case "in" if isinstance(value, (list, tuple)):
                        conditions.append(field.in_(value))

                continue

            if hasattr(self.model, key):
                conditions.append(getattr(self.model, key) == value)

        if conditions:
            query = query.filter(and_(*conditions))

        return query

    def get(self, id: UUID) -> Optional[ModelType]:
        return self.db.query(self.model).filter(self.model.id == id).first()

    def get_multi(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[dict[str, Any]] = None,
        order_by: Optional[list[str]] = None,
    ) -> List[ModelType]:

        query = self.db.query(self.model)
        query = self.apply_filters(query, filters)

        if order_by:
            for item in order_by:
                if item.startswith("-"):
                    field_name = item[1:]
                    if hasattr(self.model, field_name):
                        query = query.order_by(desc(getattr(self.model, field_name)))
                else:
                    if hasattr(self.model, item):
                        query = query.order_by(asc(getattr(self.model, item)))

        return query.offset(skip).limit(limit).all()

    def create(self, *, obj_in: CreateSchemaType) -> ModelType:
        db_obj = self.model(**obj_in.model_dump())

        try:
            self.db.add(db_obj)
            self.db.commit()
            self.db.refresh(db_obj)
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return db_obj

    def update(self, *, db_obj: ModelType, obj_in: UpdateSchemaType) -> ModelType:
        obj_data = obj_in.model_dump(exclude_unset=True)

        for field, value in obj_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        try:
            self.db.add(db_obj)
            self.db.commit()
            self.db.refresh(db_obj)
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return db_obj

    def delete(self, *, id: UUID) -> None:
        stmt = delete(self.model).where(self.model.id == id)

        try:
            self.db.execute(stmt)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def count(self, filters: Optional[dict] = None) -> int:
        query = self.db.query(self.model)
        query = self.apply_filters(query, filters)
        return query.count()
