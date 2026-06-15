from typing import List
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.models.document_chunk_link import DocumentChunkLink
from app.repositories.base import BaseRepository


class DocumentChunkLinkRepository(
    BaseRepository[DocumentChunkLink, dict, dict]
):

    BATCH_SIZE = 1000

    def __init__(self, db: Session):
        super().__init__(DocumentChunkLink, db)

    def create_link(
        self,
        document_id: UUID,
        chunk_id: UUID,
    ) -> DocumentChunkLink:
        stmt = (
            insert(DocumentChunkLink)
            .values(
                document_id=document_id,
                chunk_id=chunk_id,
            )
            .on_conflict_do_nothing(
                index_elements=["document_id", "chunk_id"]
            )
        )

        self.db.execute(stmt)
        self.db.flush()

        query = select(DocumentChunkLink).where(
            DocumentChunkLink.document_id == document_id,
            DocumentChunkLink.chunk_id == chunk_id,
            DocumentChunkLink.is_deleted.is_(False),
        )

        return self.db.execute(query).scalar_one()

    def batch_create_links(
        self,
        document_id: UUID,
        chunk_ids: List[UUID],
    ) -> int:

        if not chunk_ids:
            return 0

        unique_chunk_ids = list(set(chunk_ids))

        total_processed = 0

        for start in range(
            0,
            len(unique_chunk_ids),
            self.BATCH_SIZE,
        ):
            batch_chunk_ids = unique_chunk_ids[
                start : start + self.BATCH_SIZE
            ]

            values = [
                {
                    "document_id": document_id,
                    "chunk_id": chunk_id,
                }
                for chunk_id in batch_chunk_ids
            ]

            stmt = (
                insert(DocumentChunkLink)
                .values(values)
                .on_conflict_do_nothing(
                    index_elements=[
                        "document_id",
                        "chunk_id",
                    ]
                )
            )

            self.db.execute(stmt)

            total_processed += len(batch_chunk_ids)

        self.db.flush()

        return total_processed

    def get_links_by_document(
        self,
        document_id: UUID,
    ) -> List[DocumentChunkLink]:

        query = select(DocumentChunkLink).where(
            DocumentChunkLink.document_id == document_id,
            DocumentChunkLink.is_deleted.is_(False),
        )

        return self.db.execute(query).scalars().all()

    def delete_links_by_document(
        self,
        document_id: UUID,
    ) -> int:

        stmt = delete(DocumentChunkLink).where(
            DocumentChunkLink.document_id == document_id
        )

        result = self.db.execute(stmt)

        self.db.flush()

        return result.rowcount or 0