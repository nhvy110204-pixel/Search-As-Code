import asyncio
import json
import os
import time
from typing import List, Dict, Any
from openai import AsyncOpenAI
from app.config.settings import settings
from app.sdk.low_level.retrieval import log_sdk_operation

class LLMSDK:
    def __init__(self, config=None):
        user_api_keys = {}
        if config:
            configurable = config.get("configurable", config)
            if isinstance(configurable, dict):
                user_api_keys = configurable.get("user_api_keys") or {}

        # 1. BYOK Path: User has configured their own key
        if "openai" in user_api_keys and user_api_keys["openai"]:
            api_key = user_api_keys["openai"]
            base_url = None
        # 2. Proxy Path (Default): Use platform LiteLLM Proxy
        else:
            api_key = settings.LITELLM_PROXY_KEY
            base_url = settings.LITELLM_PROXY_URL

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model_name = settings.CHAT_MODEL_NAME

    async def extract_many(
        self,
        items: List[Dict],
        instruction: str,
        schema: Dict[str, Any],
        concurrency: int = 5
    ) -> List[Dict]:
        """
        Batch LLM structured extraction.
        Each item is extracted in parallel with concurrency control.
        """
        start_time = time.perf_counter()
        semaphore = asyncio.Semaphore(concurrency)

        async def extract_one(item: Dict) -> Dict:
            async with semaphore:
                return await self._extract_single(item, instruction, schema)

        results = await asyncio.gather(
            *[extract_one(item) for item in items],
            return_exceptions=True
        )
        
        clean_results = []
        for r in results:
            if isinstance(r, Exception):
                clean_results.append({"matches": False, "error": str(r)})
            else:
                # Wrap according to spec format
                clean_results.append({
                    "matches": True,
                    "data": r,
                    "confidence": 1.0
                })

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        log_sdk_operation(
            operation_type="extract_many",
            input_params={"instruction": instruction, "items_count": len(items)},
            result_count=len(clean_results),
            duration_ms=duration_ms
        )
        return clean_results

    async def query_llm(self, prompt: str) -> str:
        """
        Single LLM reasoning query.
        """
        start_time = time.perf_counter()
        try:
            resp = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000
            )
            content = resp.choices[0].message.content or ""
        except Exception as e:
            content = f"LLM Error: {str(e)}"

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        log_sdk_operation(
            operation_type="query_llm",
            input_params={"prompt_length": len(prompt)},
            result_count=1,
            duration_ms=duration_ms
        )
        return content

    def parse_jsonl(self, text: str) -> list:
        """Parse JSONL output from query_llm."""
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        result = []
        for line in lines:
            try:
                # Clean code fences if outputted
                clean_line = line.strip().removeprefix("```json").removesuffix("```").strip()
                result.append(json.loads(clean_line))
            except json.JSONDecodeError:
                continue
        return result

    async def _extract_single(self, item: Dict, instruction: str, schema: Dict) -> Dict:
        schema_str = json.dumps(schema, indent=2)
        prompt = f"""
{instruction}

Item:
{json.dumps(item, indent=2)}

Respond ONLY with a JSON object matching this schema:
{schema_str}
"""
        resp = await self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            response_format={"type": "json_object"}
        )
        text = resp.choices[0].message.content or ""
        return json.loads(text.strip())
