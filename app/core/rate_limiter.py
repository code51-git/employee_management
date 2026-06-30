import time
from fastapi import HTTPException, Request, status
import redis.asyncio as aioredis

redis_client = aioredis.from_url("redis://redis:6379/0", decode_responses=True)

async def rate_limiter(request: Request, limit: int = 100, window: int = 60):

    client_ip = request.client.host
    route_path = request.url.path
    key = f"rate:{client_ip}:{route_path}"
    
    current_time = int(time.time())
    
    async with redis_client.pipeline(transaction=True) as pipe:
        await pipe.zremrangebyscore(key, 0, current_time - window)
        await pipe.zcard(key)
        await pipe.zadd(key, {str(current_time): current_time})
        await pipe.expire(key, window)
        
        _, request_count, _, _ = await pipe.execute()
        
    if request_count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down."
        )