import asyncio
import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

def service_boundary(operation_name: str):
    def decorator(func: Callable[..., Any]):
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger.info(f"Starting operation: {operation_name}")
                try:
                    result = await func(*args, **kwargs)
                    logger.info(f"Successfully completed operation: {operation_name}")
                    return result
                except Exception as e:
                    logger.error(f"Failed operation [{operation_name}]: {str(e)}", exc_info=True)
                    raise RuntimeError(f"Service error during {operation_name}: {str(e)}")
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                logger.info(f"Starting operation: {operation_name}")
                try:
                    result = func(*args, **kwargs)
                    logger.info(f"Successfully completed operation: {operation_name}")
                    return result
                except Exception as e:
                    logger.error(f"Failed operation [{operation_name}]: {str(e)}", exc_info=True)
                    raise RuntimeError(f"Service error during {operation_name}: {str(e)}")
            return sync_wrapper
    return decorator