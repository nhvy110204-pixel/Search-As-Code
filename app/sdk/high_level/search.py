import asyncio
import time
from typing import List, Dict
from app.sdk.types import SearchHit

class SearchSDK:
    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key
        self.base_url = base_url

    async def web_many(
        self,
        queries: List[Dict],
        limit_per_query: int = 8,
        concurrency: int = 12
    ) -> List[List[SearchHit]]:
        """
        Execute nhiều search queries song song.
        """
        from app.sdk.low_level.retrieval import retrieve, log_sdk_operation
        start_time = time.perf_counter()
        semaphore = asyncio.Semaphore(concurrency)

        async def search_one(q: Dict) -> List[SearchHit]:
            async with semaphore:
                query_str = q.get("query") if isinstance(q, dict) else str(q)
                # Web search temporarily commented out/redirected to index for MVP
                return await retrieve(query_str, source="index", limit=limit_per_query)

        results = await asyncio.gather(
            *[search_one(q) for q in queries],
            return_exceptions=True
        )

        clean_results = []
        for r in results:
            if isinstance(r, list):
                clean_results.append(r)
            else:
                clean_results.append([])

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        log_sdk_operation(
            operation_type="web_many",
            input_params={"queries_count": len(queries), "limit_per_query": limit_per_query},
            result_count=sum(len(hits) for hits in clean_results),
            duration_ms=duration_ms
        )
        return clean_results

    async def deep_search(
        self,
        query: str,
        depth: int = 3,
        strategy: str = "breadth_first"
    ) -> List[SearchHit]:
        """
        Multi-hop iterative search: retrieve -> analyze gaps -> refine -> repeat.
        """
        from app.sdk.low_level.retrieval import retrieve, log_sdk_operation
        from app.sdk.high_level.llm import LLMSDK
        
        start_time = time.perf_counter()
        llm = LLMSDK()
        all_hits = []
        current_query = query

        for d in range(depth):
            # 1. Retrieve search results (web search temporarily commented out/redirected to index for MVP)
            hits = await retrieve(current_query, source="index", limit=5)
            all_hits.extend(hits)
            
            if d == depth - 1:
                break
                
            # 2. Ask LLM to refine query based on current gaps
            context = "\n".join([f"- {h.title}: {h.content[:150]}" for h in hits])
            prompt = f"""
Given the user search goal: "{query}"
And these current search results:
{context}

We want to search for more specific, missing details to complete the goal.
Generate ONE refined, specific search query to look up next.
Respond ONLY with the search query text, no comments.
"""
            refined = await llm.query_llm(prompt)
            refined = refined.strip().strip('"').strip()
            if not refined or refined == current_query or "LLM Error" in refined:
                break
            current_query = refined

        # Deduplicate hits by ID
        seen = set()
        unique_hits = []
        for h in all_hits:
            if h.id not in seen:
                seen.add(h.id)
                unique_hits.append(h)

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        log_sdk_operation(
            operation_type="deep_search",
            input_params={"query": query, "depth": depth, "strategy": strategy},
            result_count=len(unique_hits),
            duration_ms=duration_ms
        )
        return unique_hits
