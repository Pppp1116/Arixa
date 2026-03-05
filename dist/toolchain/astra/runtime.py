"""Tiny runtime helpers for task spawning and async execution in Python mode."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

_pool = ThreadPoolExecutor()

def spawn(fn, *args, **kwargs):
    """Schedule work on the runtime thread pool and return a future handle.
    
    Parameters:
        fn: Input value used by this routine.
        *args: Additional positional arguments.
        **kwargs: Additional keyword arguments.
    
    Returns:
        Value produced by the routine, if any.
    """
    return _pool.submit(fn, *args, **kwargs)

async def run_async(awaitable):
    """Await and return the result of an awaitable object.
    
    Parameters:
        awaitable: Input value used by this routine.
    
    Returns:
        Awaited result produced by the coroutine.
    """
    return await awaitable

def shutdown():
    """Shut down runtime worker resources gracefully.
    
    Parameters:
        none
    
    Returns:
        Value produced by the routine, if any.
    """
    _pool.shutdown(wait=True)
