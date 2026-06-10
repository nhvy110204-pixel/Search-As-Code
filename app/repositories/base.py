from typing import Generic, List, Optional, Type, TypeVar, Any, Dict
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, delete, select, func, asc, desc, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from models.base import Base, SoftDeleteMixin

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class BaseRepository(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType], db: Session):
        self.model = model
        self.db = db

    #  HELPERS 
    def _get_query(self, include_deleted: bool = False) -> Select:
        """Base query có hỗ trợ Soft Delete"""
        query = select(self.model)
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.is_deleted == False)
        return query

    def _apply_filters(self, query: Select, filters: Optional[Dict[str, Any]] = None) -> Select:
        if not filters:
            return query

        conditions = []
        for key, value in filters.items():
            if value is None:
                continue

            if "__" in key:
                
                field_name, op = key.rsplit("__", 1)
                if not hasattr(self.model, field_name):
                    continue
                field = getattr(self.model, field_name)

                if op == "like" or op == "ilike":
                    conditions.append(field.ilike(f"%{value}%"))
                elif op == "in":
                    conditions.append(field.in_(value) if isinstance(value, (list, tuple)) else field.in_([value]))
                elif op == "gte":
                    conditions.append(field >= value)
                elif op == "gt":
                    conditions.append(field > value)
                elif op == "lte":
                    conditions.append(field <= value)
                elif op == "lt":
                    conditions.append(field < value)
                elif op == "is_null":
                    conditions.append(field.is_(None))
                elif op == "is_not_null":
                    conditions.append(field.is_not(None))
            else:
                if hasattr(self.model, key):
                    conditions.append(getattr(self.model, key) == value)

        if conditions:
            query = query.where(and_(*conditions))
        return query

    def _apply_ordering(self, query: Select, order_by: Optional[List[str]] = None) -> Select:
        if not order_by:
            return query

        for item in order_by:
            if item.startswith("-"):
                field_name = item[1:]
                direction = desc
            else:
                field_name = item
                direction = asc

            if hasattr(self.model, field_name):
                query = query.order_by(direction(getattr(self.model, field_name)))
        return query

    #  READ OPERATIONS 
    def get(self, id: UUID, include_deleted: bool = False, options: List = None) -> Optional[ModelType]:
        query = self._get_query(include_deleted).where(self.model.id == id)
        if options:
            query = query.options(*options)
        return self.db.execute(query).scalars().first()

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
        query = self._get_query(include_deleted)
        query = self._apply_filters(query, filters)
        query = self._apply_ordering(query, order_by)

        if options:
            query = query.options(*options)

        return self.db.execute(query.offset(skip).limit(limit)).scalars().all()

    def count(self, filters: Optional[Dict] = None, include_deleted: bool = False) -> int:
        query = select(func.count()).select_from(self.model)
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.is_deleted == False)
        query = self._apply_filters(query, filters)
        return self.db.scalar(query)

    def exists(self, filters: Dict[str, Any]) -> bool:
        query = select(1).select_from(self.model)
        query = self._apply_filters(query, filters)
        return self.db.scalar(query) is not None

    def get_by(self, **filters) -> Optional[ModelType]:
        query = self._get_query()
        query = self._apply_filters(query, filters)
        return self.db.execute(query).scalars().first()

    #  WRITE OPERATIONS (Chuẩn ACID) 
    def create(self, obj_in: CreateSchemaType) -> ModelType:
        """Tạo mới object - Chỉ flush để sinh ID, tuyệt đối không commit tại đây"""
        db_obj = self.model(**obj_in.model_dump(exclude_unset=True))
        self.db.add(db_obj)
        self.db.flush()  # Đẩy xuống DB tạm thời
        self.db.refresh(db_obj)
        return db_obj

    def update(self, db_obj: ModelType, obj_in: UpdateSchemaType | Dict[str, Any]) -> ModelType:
        """Cập nhật dữ liệu - Chỉ flush, không tự ý commit"""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        self.db.add(db_obj)
        self.db.flush()
        self.db.refresh(db_obj)
        return db_obj

    def soft_delete(self, id: UUID) -> bool:
        """Tối ưu bằng câu lệnh UPDATE trực tiếp, tiết kiệm 1 query SELECT"""
        if not issubclass(self.model, SoftDeleteMixin):
            return False

        stmt = (
            update(self.model)
            .where(self.model.id == id, self.model.is_deleted == False)
            .values(is_deleted=True, deleted_at=func.now())
        )
        result = self.db.execute(stmt)
        self.db.flush()
        return result.rowcount > 0

    def hard_delete(self, id: UUID) -> bool:
        """Xóa vĩnh viễn bản ghi khỏi DB - Chỉ gọi flush"""
        stmt = delete(self.model).where(self.model.id == id)
        result = self.db.execute(stmt)
        self.db.flush()
        return result.rowcount > 0