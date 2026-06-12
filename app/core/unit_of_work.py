from contextlib import AbstractContextManager
from sqlalchemy.orm import Session
import logging

from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)


class UnitOfWork(AbstractContextManager):

    def __init__(self, db: Session, read_only: bool = False):
        self.db: Session = db
        self.read_only = read_only
        self._committed = False
        # add repositories
        self.users = UserRepository(self.db)

    def __enter__(self):
        logger.debug("Entering UnitOfWork (read_only=%s)", self.read_only)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                if self.read_only:
                    logger.debug("UnitOfWork read-only: rolling back to discard changes")
                    try:
                        self.db.rollback()
                    except Exception:
                        logger.exception("Failed to rollback read-only UnitOfWork")
                else:
                    logger.debug("UnitOfWork committing transaction")
                    try:
                        self.db.commit()
                        self._committed = True
                    except Exception:
                        logger.exception("Commit failed in UnitOfWork; rolling back")
                        self.db.rollback()
                        raise
            else:
                logger.debug("UnitOfWork exiting with exception; rolling back")
                try:
                    self.db.rollback()
                except Exception:
                    logger.exception("Failed to rollback UnitOfWork after exception")
        finally:
            return False

    def commit(self):
        logger.debug("UnitOfWork explicit commit")
        self.db.commit()
        self._committed = True

    def rollback(self):
        logger.debug("UnitOfWork explicit rollback")
        self.db.rollback()
