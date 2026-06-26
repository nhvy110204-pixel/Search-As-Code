from uuid import UUID
from typing import Dict, Any
import logging
from openai import AsyncOpenAI
from app.config.settings import settings
from app.observability.metrics import track_cost, track_step_duration
from app.core.utils import get_chat_cost

logger = logging.getLogger(__name__)


@track_step_duration("summary")
async def summary_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state
) -> Dict[str, Any]:

    document = uow.documents.get(document_id)
    
    if not document:
        raise ValueError(f"Document {document_id} not found")
    
    if not document.markdown_content:
        raise ValueError(f"Document {document_id} has no markdown content")
    
    if not settings.LITELLM_PROXY_KEY:
        logger.warning("LiteLLM Proxy key not configured, using placeholder summary")
        content_length = len(document.markdown_content)
        summary = f"Document with {content_length} characters (LiteLLM Proxy not configured)"
        pipeline_state.global_summary = summary
        return {"global_summary": summary}
    
    try:
        client = AsyncOpenAI(
            api_key=settings.LITELLM_PROXY_KEY,
            base_url=settings.LITELLM_PROXY_URL
        )
        
        content = document.markdown_content
        max_chars = 10000  # Approx 4000 tokens
        if len(content) > max_chars:
            content = content[:max_chars] + "..."
        
        response = await client.chat.completions.create(
            model=settings.CHAT_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that summarizes documents concisely. Provide a 2-3 sentence summary of the main topic and key points."
                },
                {
                    "role": "user",
                    "content": f"Summarize this document:\n\n{content}"
                }
            ],
            max_tokens=300,
            temperature=0.3
        )
        
        summary = response.choices[0].message.content.strip()
        
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            cost = get_chat_cost(prompt_tokens, completion_tokens, settings.CHAT_MODEL_NAME)
            track_cost("summarization", cost)
        else:
            input_tokens = len(content) // 4
            output_tokens = len(summary) // 4
            cost = get_chat_cost(input_tokens, output_tokens, settings.CHAT_MODEL_NAME)
            track_cost("summarization", cost)
        
        pipeline_state.global_summary = summary
        
        logger.info(f"Generated OpenAI summary for document {document_id}")
        
    except Exception as e:
        logger.error(f"OpenAI summarization failed for document {document_id}: {e}")
        content_length = len(document.markdown_content)
        summary = f"Document with {content_length} characters (OpenAI failed: {str(e)})"
        pipeline_state.global_summary = summary
    
    return {"global_summary": pipeline_state.global_summary}
