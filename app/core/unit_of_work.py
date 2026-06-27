from contextlib import AbstractContextManager
from sqlalchemy.orm import Session
import logging

from app.repositories.user import UserRepository
from app.repositories.project import ProjectRepository
from app.repositories.document import DocumentRepository
from app.repositories.document_chunk import DocumentChunkRepository
from app.repositories.document_chunk_link import DocumentChunkLinkRepository
from app.repositories.ingestion_task import IngestionTaskRepository
from app.repositories.chat_session import ChatSessionRepository
from app.repositories.chat_message import ChatMessageRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.api_key import APIKeyRepository

logger = logging.getLogger(__name__)


class UnitOfWork(AbstractContextManager):

    def __init__(self, db: Session, read_only: bool = False):
        self.db: Session = db
        self.read_only = read_only
        self._committed = False
        # add repositories
        self.users = UserRepository(self.db)
        self.projects = ProjectRepository(self.db)
        self.documents = DocumentRepository(self.db)
        self.document_chunks = DocumentChunkRepository(self.db)
        self.document_chunk_links = DocumentChunkLinkRepository(self.db)
        self.ingestion_tasks = IngestionTaskRepository(self.db)
        self.chat_sessions = ChatSessionRepository(self.db)
        self.chat_messages = ChatMessageRepository(self.db)
        self.audit_logs = AuditLogRepository(self.db)
        self.api_keys = APIKeyRepository(self.db)

    def __enter__(self):
        logger.debug("Entering UnitOfWork (read_only=%s)", self.read_only)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
            try:
                if exc_type is not None:
                    logger.debug("UnitOfWork exiting with exception; rolling back")
                    self.db.rollback()
                    return False 

                if self.read_only:
                    logger.debug("UnitOfWork read-only: rolling back to discard changes")
                    self.db.rollback()
                else:
                    logger.debug("UnitOfWork committing transaction")
                    self.db.commit()
                    self._committed = True
            except Exception:
                logger.exception("Error occurred during UnitOfWork exit processing")
                self.db.rollback()
                raise

    def commit(self):
        logger.debug("UnitOfWork explicit commit")
        self.db.commit()
        self._committed = True

    def rollback(self):
        logger.debug("UnitOfWork explicit rollback")
        self.db.rollback()
