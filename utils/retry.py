import time
import functools
from typing import Callable, Tuple, Type, Any

from utils.logger import get_logger

logger = get_logger("utils.retry")



def with_retry(
    max_attempts: int = 3,
    delay_seconds: float = 2.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    log_attempts: bool = True,
) -> Callable:

    if max_attempts <1:
        raise ValueError("max_attempts must be at least 1")
    if delay_seconds<0:
        raise ValueError("delay_seconds must be non-negative")
    if backoff_factor<1:
        raise ValueError("backoff_factor must be at least 1")

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args:Any, **kwargs:Any)->Any:
            last_exceptions:Exception | None = None
            current_delay = delay_seconds

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc
                    if attempt < max_attempts:
                        if log_attempts:
                            logger.warning(
                                f"{func.__qualname__} attempt {attempt} /{max_attempts}"
                                f"failed: {type(exc).__name__}: {exc}"
                                F"Retrying in {current_delay} seconds..."
                            )

                        time.sleep(current_delay)
                        current_delay += backoff_factor
                    else:
                        logger.error(
                            f"{func.__qualname__} failed after {max_attempts}"
                            f"attempts. Last error: {type{exc}.__name__}: {exc}"
                        )
                
            raise last_exception
        
        return wrapper
    
return decorator


