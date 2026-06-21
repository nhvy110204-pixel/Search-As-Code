import os
import time
import uuid
import asyncio
from typing import List, Dict, Any, Optional
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.sdk_operation import SDKOperation
from app.sdk.types import SearchHit

def log_sdk_operation(
    operation_type: str,
    input_params: Dict[str, Any],
    result_count: Optional[int],
    duration_ms: Optional[int],
    cost_usd: Optional[float] = None
):
    import sys
    from app.config.settings import settings
    if "pytest" in sys.modules or settings.APP_ENV == "test" or os.environ.get("APP_ENV") == "test":
        return

    task_id_str = os.environ.get("TASK_ID")
    if not task_id_str:
        return
    try:
        task_id = uuid.UUID(task_id_str)
    except Exception:
        return

    turn_number_str = os.environ.get("TURN_NUMBER", "1")
    try:
        turn_number = int(turn_number_str)
    except Exception:
        turn_number = 1

    db = SessionLocal()
    try:
        op = SDKOperation(
            task_id=task_id,
            turn_number=turn_number,
            operation_type=operation_type,
            input_params=input_params,
            result_count=result_count,
            duration_ms=duration_ms,
            cost_usd=Decimal(str(cost_usd)) if cost_usd is not None else None
        )
        db.add(op)
        db.commit()
    except Exception as e:
        import sys
        print(f"Error logging SDK operation to database: {e}", file=sys.stderr)
        db.rollback()
    finally:
        db.close()

async def retrieve(
    query: str,
    source: str = "index",   # Default to index for MVP. "web" is disabled.
    limit: int = 10
) -> List[SearchHit]:
    """Atomic single-source retrieval. Queries Qdrant or simulated web search."""
    start_time = time.perf_counter()
    hits = []

    try:
        # Check source. Web search is temporarily disabled for MVP.
        # If source is "web", redirect it to "index" for document-only search.
        effective_source = source
        if source == "web":
            # Web search is temporarily commented out for post-MVP. We default to index search.
            effective_source = "index"

        if effective_source in {"index", "embedding_store"}:
            from app.rag.embeddings.manager import EmbeddingManager
            from app.core.qdrant import qdrant_manager
            from app.config.settings import settings

            # Generate query embedding
            provider = EmbeddingManager.get_provider(async_mode=False)
            query_vector = provider.embed_text(query)

            # Search vector store
            results = qdrant_manager.search_vectors(
                collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                query_vector=query_vector,
                limit=limit,
                score_threshold=0.0
            )

            for res in results:
                payload = res.get("payload", {})
                hits.append(SearchHit(
                    id=str(res.get("embedding_id")),
                    title=payload.get("title", f"Chunk {payload.get('chunk_index', 0)}"),
                    content=payload.get("content", ""),
                    url=payload.get("url", None),
                    score=res.get("score", 1.0),
                    metadata={
                        "document_id": payload.get("document_id"),
                        "project_id": payload.get("project_id"),
                        "chunk_index": payload.get("chunk_index")
                    }
                ))

        else:
            # Simulated Web Search results commented out for post-MVP.
            pass
            # query_lower = query.lower()
            # if "cve-2023-38606" in query_lower or ("apple" in query_lower and "kernel" in query_lower):
            #     hits = [
            #         SearchHit(
            #             id="web-cve-2023-38606-1",
            #             title="Apple Security Advisory: CVE-2023-38606 Exploit Patch",
            #             content="Apple has released security updates for iOS, iPadOS, macOS, and watchOS to address CVE-2023-38606, an actively exploited zero-day vulnerability in the kernel. This state-corruption flaw in the kernel allows a malicious application to modify sensitive kernel variables and bypass code signing checks.",
            #             url="https://support.apple.com/en-us/HT213841",
            #             score=0.98,
            #             metadata={"vendor": "apple", "severity": "critical"}
            #         ),
            #         SearchHit(
            #             id="web-cve-2023-38606-2",
            #             title="NVD CVE-2023-38606 Detail",
            #             content="NVD description: A validation issue was addressed with improved input sanitization. This issue is fixed in iOS 16.6 and iPadOS 16.6, macOS Ventura 13.5. An app may be able to modify sensitive kernel state. Apple is aware of a report that this issue may have been actively exploited.",
            #             url="https://nvd.nist.gov/vuln/detail/CVE-2023-38606",
            #             score=0.95,
            #             metadata={"vendor": "nvd", "severity": "high"}
            #         )
            #     ]
            # elif "cve" in query_lower:
            #     hits = [
            #         SearchHit(
            #             id="web-generic-cve",
            #             title="CVE Vulnerability database reference",
            #             content="Generic vulnerability reference. Common Vulnerabilities and Exposures (CVE) is a dictionary of common names for publicly known cybersecurity vulnerabilities.",
            #             url="https://cve.mitre.org",
            #             score=0.8
            #         )
            #     ]
            # else:
            #     # General search results
            #     hits = [
            #         SearchHit(
            #             id=f"web-generic-{i}",
            #             title=f"Search result for: {query[:30]}",
            #             content=f"This is a simulated web search result containing relevant content for query: {query}",
            #             url=f"https://example.com/search?q={query[:10]}",
            #             score=0.75 - (i * 0.05)
            #         )
            #         for i in range(min(limit, 3))
            #     ]

        # Enforce limit
        hits = hits[:limit]

    finally:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        # Log this operation into database
        log_sdk_operation(
            operation_type="retrieve",
            input_params={"query": query, "source": source, "limit": limit},
            result_count=len(hits),
            duration_ms=duration_ms
        )

        # Write to STATE_DIR if available for graph validators
        state_dir_str = os.environ.get("STATE_DIR")
        turn_number_str = os.environ.get("TURN_NUMBER", "1")
        if state_dir_str:
            try:
                import json
                from pathlib import Path
                state_dir = Path(state_dir_str)
                hits_file = state_dir / f"retrieved_hits_turn_{turn_number_str}.json"
                hits_data = [
                    {
                        "id": h.id,
                        "title": h.title,
                        "content": h.content,
                        "url": h.url,
                        "score": h.score,
                        "metadata": h.metadata
                    } for h in hits
                ]
                hits_file.write_text(json.dumps(hits_data))
            except Exception as e:
                import sys
                print(f"Error writing retrieved hits to state dir: {e}", file=sys.stderr)

    return hits

async def fanout(
    base_query: str,
    variants: List[str],
    concurrency: int = 12
) -> List[SearchHit]:
    """
    Fan-out: expand a query into variants, retrieve them in parallel, flatten and unique.
    """
    from app.sdk.utils import flatten, unique
    
    semaphore = asyncio.Semaphore(concurrency)
    
    async def one_variant(variant: str) -> List[SearchHit]:
        async with semaphore:
            query = variant.format(q=base_query) if "{q}" in variant else f"{variant} {base_query}"
            # Web search temporarily commented out/redirected to index for MVP
            return await retrieve(query=query, source="index")

    results = await asyncio.gather(*[one_variant(v) for v in variants], return_exceptions=True)
    
    # Filter exceptions
    clean_results = []
    for r in results:
        if isinstance(r, list):
            clean_results.append(r)
            
    flat = flatten(clean_results)
    
    # Deduplicate by content or ID
    seen_ids = set()
    deduped = []
    for hit in flat:
        if hit.id not in seen_ids:
            seen_ids.add(hit.id)
            deduped.append(hit)
            
    return deduped
