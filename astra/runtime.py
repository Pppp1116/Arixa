import asyncio
from concurrent.futures import ThreadPoolExecutor

_pool = ThreadPoolExecutor()

def spawn(fn, *args, **kwargs):
    return _pool.submit(fn, *args, **kwargs)

async def run_async(awaitable):
    return await awaitable

def shutdown():
    _pool.shutdown(wait=True)
