**CRUD Pattern (End-to-End)**

This document describes the canonical CRUD pattern used across the codebase, illustrated with the `User` CRUD implementation. Follow this pattern when adding new domain models (Project, Document, DocumentChunk, etc.).

**Overview**
- **Purpose:** Provide a single, testable, production-ready flow: Model → Repository → Service → Controller.
- **Goals:** clear separation of concerns, consistent pagination, and predictable error mapping.
- **Architecture:** Repository returns Model, Service converts Model to Schema, Controller returns Schema.

**Files & Locations**
- **Model:** [app/models/<model>.py](app/models/)
- **DTOs (Pydantic):** [app/schemas/dto/<model>.py](app/schemas/dto/)
- **Repository:** [app/repositories/<model>.py](app/repositories/)
- **Service:** [app/services/core/<model>.py](app/services/core/)
- **Base Service:** [app/services/core/base.py](app/services/core/base.py)
- **Unit of Work:** [app/core/unit_of_work.py](app/core/unit_of_work.py)
- **Controllers:** [app/api/controllers/<model>.py](app/api/controllers/)

**Pattern Details**
- **Model:** define columns, relationships and mixins in `app/models` (e.g. [app/models/user.py](app/models/user.py)).
- **DTOs:** separate `Create`/`Update`/`Response` and use `model_config = ConfigDict(from_attributes=True)` for response DTOs so Pydantic can read ORM attributes directly (see [app/schemas/dto/user.py](app/schemas/dto/user.py)).
- **BaseRepository:** implements filtered `get_multi`, `count`, `get`, `create`, `update`, `soft_delete` and helpers for filtering/ordering. Keep it DB-agnostic and only `flush()` on `create`/`update` (no commits).
- **Repository (concrete):** implement domain-specific read helpers and pagination wrapper. Example methods:
  - `get_user(id)` — wrapper for `BaseRepository.get`.
  - `list_users(page, page_size, filters)` — returns `tuple[list[Model], int]`. The repository should be DB-focused and return Model objects only; the service is responsible for converting to response DTOs like `UserListResponse`. File: [app/repositories/user.py](app/repositories/user.py).
- **BaseService:** generic CRUD operations with dependency injection. Provides `get()`, `get_multi()`, `create()`, `update()`, `delete()` methods. File: [app/services/core/base.py](app/services/core/base.py).
- **Service (concrete):** extend `BaseService` and implement **only domain-specific business logic**. Override `create()` only if there's business logic (e.g., password hashing). Implement domain methods for use cases:
  - ✅ Override `create()` if validation/transformation needed (e.g., `UserService.create()` hashes password)
  - ❌ Do NOT override `get()`, `update()`, `delete()` just to forward calls
  - ✅ Implement domain methods (e.g., `authenticate()`, `get_users_paginated()`)
  - ✅ Convert Model to Schema in pagination methods
  - Example: [app/services/core/user.py](app/services/core/user.py)
- **UnitOfWork:** single place to manage transaction semantics. Use `read_only` flag to prevent commits on read flows. File: [app/core/unit_of_work.py](app/core/unit_of_work.py).
- **Controllers (handlers + router):** define `APIRouter` and route handlers in `app/api/controllers/<model>.py`. Controllers may include dependency helpers (service factories using `UnitOfWork`) and map service errors to HTTP responses.
- **Router registry:** central router file (e.g. [main.py](main.py)) should compose and register controller routers via `include_router()`. Keep registration files thin — controllers own the handlers.

**Transactions & Read-Only Flows**
- Transaction boundaries are in `UnitOfWork`. For read endpoints use `UnitOfWork(db, read_only=True)` so any accidental writes are rolled back.
- For write flows wrap logic in `with UnitOfWork(db) as uow: service = Service(repository=uow.<models>) ...` and let the UoW commit on successful exit.

**Pagination & Responses**
- Keep pagination logic in repository: implement `list_<models>(page, page_size, filters)` returning `tuple[list[Model], int]`.
- Service converts Model to Schema: implement `get_<models>_paginated()` that calls repository and converts to response DTO (items + total + page info). This avoids duplicating `count()`/`skip` logic across services and maintains clear separation of concerns.

**Error Handling**
- Services should raise domain errors or let DB exceptions bubble; routes are responsible for mapping `IntegrityError` and other DB exceptions to appropriate HTTP codes.

**Security**
- Hash passwords with `passlib[bcrypt]` in `app/core/security.py` before persisting (`get_password_hash`, `verify_password`).
- Never log sensitive fields (passwords, secrets); sanitize request/response logging.
- Add authorization checks in controllers to ensure users can only access their own resources.

**Testing**
- Unit tests: mock repositories for services, test business logic. File pattern: `tests/unit/services/test_<model>_service.py`.
- Integration tests: use a test DB fixture and UoW; ensure tests rollback transactions between tests. File pattern: `tests/integration/test_<model>_endpoints.py`.

**Service Pattern Best Practices**

**BaseService Is Internal CRUD Layer**
```python
class BaseService(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """Generic CRUD operations, not exposed directly."""
    def __init__(self, repository):
        self.repo = repository
    
    def get(self, id: UUID) -> Optional[ModelType]:
        return self.repo.get(id=id)
    
    def create(self, obj_in: CreateSchemaType) -> ModelType:
        return self.repo.create(obj_in)
    
    def update(self, id: UUID, obj_in: UpdateSchemaType) -> Optional[ModelType]:
        db_obj = self.repo.get(id)
        if not db_obj:
            return None
        return self.repo.update(db_obj, obj_in)
    
    def delete(self, id: UUID, hard: bool = False) -> bool:
        return self.repo.hard_delete(id) if hard else self.repo.soft_delete(id)
```

**Service Exposes Domain Methods**
```python
class UserService(BaseService[User, UserCreate, UserUpdate]):
    """Override create for business logic, add domain methods."""
    
    def __init__(self, repository: UserRepository):
        super().__init__(repository)
    
    def create(self, obj_in: UserCreate) -> User:
        """Override: password hashing is business logic."""
        hashed = get_password_hash(obj_in.password)
        internal = UserCreateInternal(
            email=obj_in.email,
            username=obj_in.username,
            full_name=obj_in.full_name,
            avatar_url=obj_in.avatar_url,
            hashed_password=hashed,
            is_active=obj_in.is_active,
        )
        return self.repo.create_user(internal)
    
    def authenticate(self, email: str, password: str) -> Optional[User]:
        """Domain method: user authentication."""
        user = self.repo.get_by(email=email)
        if user and verify_password(password, user.hashed_password):
            return user
        return None
    
    def get_users_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> UserListResponse:
        """Domain method: paginated user list with Model to Schema conversion."""
        from app.schemas.dto.user import UserResponse
        users, total = self.repo.list_users(page=page, page_size=page_size, filters=filters)
        user_responses = [UserResponse.model_validate(u) for u in users]
        return UserListResponse(
            items=user_responses,
            total=total,
            page=page,
            page_size=page_size
        )
    
    # DO NOT override get(), update(), delete() unless there's domain logic!
```

**Controllers & Router Registration**

Controller files own the `APIRouter` and handlers. Handlers should be thin and delegate to services; controllers may provide dependency helpers that construct `UserService` (or other services) using a `UnitOfWork` context. Keep central router files (e.g. `main.py`) responsible only for composing and registering controller routers via `include_router()`.

Example controller (`app/api/controllers/users.py`):
```python
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.unit_of_work import UnitOfWork
from app.core.database import get_db
from app.services.core.user import UserService

router = APIRouter(prefix="/users")

def get_user_service(db=Depends(get_db)):
    with UnitOfWork(db) as uow:
        yield UserService(repository=uow.users)

@router.post("/", response_model=UserResponse)
def create_user(payload: UserCreate, service: UserService = Depends(get_user_service)):
    try:
        return service.create(payload)
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Email already exists")

@router.get("/", response_model=UserListResponse)
def list_users(
    page: int = 1,
    page_size: int = 100,
    service: UserService = Depends(get_user_service)
):
    return service.get_users_paginated(page=page, page_size=page_size)
```

Central router registry (`main.py`):
```python
from fastapi import APIRouter
from app.api.controllers.users import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(users_router)
```

**CLI / Local Commands**
Install dependencies and run migrations locally:
```bash
poetry install
poetry run python -m alembic upgrade head
```

Run tests:
```bash
poetry run pytest -q
```

**Example End-to-End Flow (Create User)**
1. Client POSTs `UserCreate` payload to `/api/v1/users`.
2. Route `create_user` obtains `db` via `get_db` and enters `with UnitOfWork(db) as uow:`.
3. Route constructs `UserService(repository=uow.users)` and calls `service.create(payload)`.
4. `UserService.create` hashes password (`app/core/security.py`) and calls `uow.users.create_user(internal_model)`.
5. Repository `create_user` flushes the new ORM object and returns it.
6. `UnitOfWork.__exit__` commits the transaction on success; route returns `UserResponse` DTO.

**Example End-to-End Flow (List Users)**
1. Client GETs `/api/v1/users?page=1&page_size=20`.
2. Route `list_users` obtains `UserService` via dependency injection.
3. Route calls `service.get_users_paginated(page=1, page_size=20)`.
4. Service calls `self.repo.list_users(page=1, page_size=20)` which returns `tuple[list[User], int]`.
5. Service converts Model to Schema: `[UserResponse.model_validate(u) for u in users]`.
6. Service returns `UserListResponse` DTO to controller.
7. Controller returns `UserListResponse` to client.

**Checklist before production**
- Add unit + integration tests for all CRUD flows.
- Add auth (JWT) + protected routes.
- Add authorization checks in controllers for resource ownership.
- CI: tests, linting, dependency scanning.
- Secrets: use Vault/Secret Manager; ensure no secrets commited.
- Observability: metrics & tracing, avoid sensitive logs.
- Service classes only override methods with business logic, reuse BaseService for generic CRUD.
- Repository methods return Model objects, not Schema DTOs.
- Service methods convert Model to Schema before returning.

Follow this pattern for new models to keep code consistent, testable and production-ready.
