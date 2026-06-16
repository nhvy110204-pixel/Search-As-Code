from __future__ import annotations
import os

from app.sdk.high_level.search import SearchSDK
from app.sdk.high_level.llm import LLMSDK
from app.sdk.low_level.retrieval import retrieve, fanout
from app.sdk.low_level.processing import rank, dedupe, embed
from app.sdk.low_level.transform import cluster, chunk, parse_field
from app.sdk.utils import (
    join_result_fields,
    flatten,
    unique,
    summarize,
    infer_vendor,
    official_vendor_advisory
)

class SDK:
    def __init__(self, config=None):
        from app.config.settings import settings
        
        # Initialize search configuration
        # For simplicity, default to settings variables or localhost API
        self.search = SearchSDK(
            api_key=settings.OPENAI_API_KEY or "",
            base_url=f"http://localhost:{os.environ.get('PORT', '8000')}/api/v1" if 'os' in globals() else "http://localhost:8000/api/v1"
        )
        self.llm = LLMSDK(config=config)

    # Low-level primitives
    retrieve = staticmethod(retrieve)
    fanout = staticmethod(fanout)
    rank = staticmethod(rank)
    dedupe = staticmethod(dedupe)
    embed = staticmethod(embed)
    cluster = staticmethod(cluster)
    chunk = staticmethod(chunk)
    parse_field = staticmethod(parse_field)

    # Utilities
    join_result_fields = staticmethod(join_result_fields)
    flatten = staticmethod(flatten)
    unique = staticmethod(unique)
    summarize = staticmethod(summarize)
    infer_vendor = staticmethod(infer_vendor)
    official_vendor_advisory = staticmethod(official_vendor_advisory)

# Expose a static global instance of the SDK
sdk = SDK()
