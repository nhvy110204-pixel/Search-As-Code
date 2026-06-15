import tiktoken
from typing import List

def count_tokens(text: str, model_name: str = "gpt-4o-mini") -> int:
    if not text or not text.strip():
        return 0
    try:
        encoding = tiktoken.encoding_for_model(model_name)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))

def count_tokens_batch(texts: List[str], model_name: str = "gpt-4o-mini") -> int:
    if not texts:
        return 0
    try:
        encoding = tiktoken.encoding_for_model(model_name)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    
    total_tokens = 0
    for text in texts:
        if text and text.strip():
            total_tokens += len(encoding.encode(text))
    return total_tokens

def get_embedding_cost(tokens: int, model_name: str = "text-embedding-3-small") -> float:
    # Pricing per token TODO: feature to add pricing from database 
    pricing = {
        "text-embedding-3-small": 0.020 / 1_000_000,
        "text-embedding-3-large": 0.130 / 1_000_000,
        "text-embedding-ada-002": 0.100 / 1_000_000,
    }
    rate = pricing.get(model_name.lower(), 0.020 / 1_000_000)
    return tokens * rate

def get_chat_cost(prompt_tokens: int, completion_tokens: int, model_name: str = "gpt-4o-mini") -> float:
    pricing = {
        "gpt-4o-mini": (0.150 / 1_000_000, 0.600 / 1_000_000),
        "gpt-4o": (2.500 / 1_000_000, 10.000 / 1_000_000),
        "gpt-4-turbo": (10.000 / 1_000_000, 30.000 / 1_000_000),
    }

    input_rate, output_rate = pricing.get(model_name.lower(), (0.150 / 1_000_000, 0.600 / 1_000_000))
    return (prompt_tokens * input_rate) + (completion_tokens * output_rate)
