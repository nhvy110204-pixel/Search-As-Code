from typing import List, Dict, Any
import asyncio
from app.sdk.types import SearchHit
from app.rag.embeddings.manager import EmbeddingManager

def rank(
    hits: List[SearchHit],
    method: str = "hybrid",   # "bm25" | "semantic" | "hybrid"
    top_k: int = 20
) -> List[SearchHit]:
    """Rerank hits based on relevance score."""
    # Simple score-based sort
    sorted_hits = sorted(hits, key=lambda h: h.score, reverse=True)
    return sorted_hits[:top_k]

def dedupe(
    items: List[Any],
    key: str = "url"
) -> List[Any]:
    """Deduplicate list of dicts or objects by an arbitrary key."""
    seen = set()
    result = []
    for item in items:
        if isinstance(item, dict):
            val = item.get(key)
        else:
            val = getattr(item, key, None)
        if val not in seen:
            seen.add(val)
            result.append(item)
    return result

async def embed(
    texts: List[str],
    model: str = "default"
) -> List[List[float]]:
    """Generate embeddings for a list of texts using the configured provider."""
    if not texts:
        return []
        
    provider = EmbeddingManager.get_provider(async_mode=True)
    
    # Run async embedding if supported natively
    if hasattr(provider, "embed_texts") and asyncio.iscoroutinefunction(provider.embed_texts):
        return await provider.embed_texts(texts)
    else:
        # Fallback to running the sync provider in a thread pool
        sync_provider = EmbeddingManager.get_provider(async_mode=False)
        return await asyncio.to_thread(sync_provider.embed_texts, texts)
