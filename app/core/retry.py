import asyncio
import functools
import logging
import random
import time
from typing import Callable, Any, Tuple, Type, Optional

from app.core.exceptions import (
    ProviderError,
    ProviderAuthError,
    ProviderInvalidInputError,
)

logger = logging.getLogger(__name__)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    jitter: bool = True,
    timeout_seconds: Optional[float] = 30.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (
        ProviderAuthError,
        ProviderInvalidInputError,
        KeyboardInterrupt,
        asyncio.CancelledError,
    )
):
    """
    Production-grade Async Retry Decorator with Exponential Backoff, Full Jitter, and Timeout.
    Automatically respects is_retryable flag on RAGFlashException hierarchy.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception: Optional[Exception] = None

            for attempt in range(1, max_retries + 1):
                try:
                    if timeout_seconds and timeout_seconds > 0:
                        return await asyncio.wait_for(
                            func(*args, **kwargs),
                            timeout=timeout_seconds
                        )
                    else:
                        return await func(*args, **kwargs)

                except non_retryable_exceptions as non_ret_err:
                    logger.warning(
                        f"Non-retryable error in {func.__name__} (attempt {attempt}/{max_retries}): {non_ret_err}"
                    )
                    raise non_ret_err

                except asyncio.TimeoutError as timeout_err:
                    last_exception = timeout_err
                    logger.warning(
                        f"Timeout of {timeout_seconds}s exceeded in {func.__name__} (attempt {attempt}/{max_retries})"
                    )

                except retryable_exceptions as err:
                    # Check custom is_retryable attribute if present on exception
                    if hasattr(err, "is_retryable") and not err.is_retryable:
                        logger.warning(
                            f"Exception flagged as non-retryable in {func.__name__}: {err}"
                        )
                        raise err

                    last_exception = err
                    logger.warning(
                        f"Error in {func.__name__} (attempt {attempt}/{max_retries}): {err}"
                    )

                if attempt < max_retries:
                    # Calculate exponential backoff delay with full jitter
                    calculated_delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    delay = random.uniform(0, calculated_delay) if jitter else calculated_delay
                    logger.info(f"Retrying {func.__name__} in {delay:.2f}s (attempt {attempt + 1}/{max_retries})...")
                    await asyncio.sleep(delay)

            # All attempts exhausted
            logger.error(
                f"Function {func.__name__} failed permanently after {max_retries} attempts. Last error: {last_exception}"
            )
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed after {max_retries} retries.")

        return wrapper
    return decorator
