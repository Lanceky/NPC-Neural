"""Process-wide token-bucket limiter for the shared free-tier lite-model
quota (15 requests/minute). Background ticks, quota-degraded principal
ticks, and on-demand /api/inspect calls all draw from this one model's
quota, so throttling requests before they're sent beats reacting to 429s
after the fact.
"""

import asyncio
import time


class RateLimiter:
    def __init__(self, max_per_minute: float):
        self._interval = 60.0 / max_per_minute
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            start = max(now, self._next_slot)
            self._next_slot = start + self._interval
            wait = start - now
        if wait > 0:
            await asyncio.sleep(wait)


# Small safety margin under the hard 15/minute cap.
lite_model_limiter = RateLimiter(max_per_minute=13)
