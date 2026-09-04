import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable

from fastapi import HTTPException, Request, status

from .config import ENVIRONMENT


@dataclass
class _Bucket:
    hits: deque = field(default_factory=lambda: deque())


class RateLimiter:
    """In-memory sliding-window rate limiter keyed by (scope, client).

    Tracks request timestamps per key and rejects requests that exceed
    `limit` within a trailing `window` of seconds. It is a per-process
    limiter suitable for single-instance deployments; for multi-instance
    setups the audit-log or an external store should be layered on top.
    """

    def __init__(self, name: str, limit: int, window: int):
        self.name = name
        self.limit = limit
        self.window = window
        self._buckets: dict = defaultdict(_Bucket)
        self._lock = threading.Lock()

    def key_for(self, request: Request) -> str:
        client = request.client.host if request.client else "unknown"
        return f"{self.name}:{client}"

    def _prune(self, bucket: _Bucket, now: float) -> None:
        cutoff = now - self.window
        while bucket.hits and bucket.hits[0] <= cutoff:
            bucket.hits.popleft()

    def check(self, request: Request) -> None:
        now = time.monotonic()
        key = self.key_for(request)
        with self._lock:
            bucket = self._buckets[key]
            self._prune(bucket, now)
            if len(bucket.hits) >= self.limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="rate limit exceeded",
                    headers={"Retry-After": str(int(self.window))},
                )
            bucket.hits.append(now)


def make_limiter(name: str, limit: int, window: int) -> Callable[[Request], None]:
    """Build a FastAPI dependency enforcing `limit` requests per `window` seconds.

    Rate limiting is disabled in the test environment so unit/integration
    tests exercise the endpoints unhindered while production stays protected.
    """
    limiter = RateLimiter(name=name, limit=limit, window=window)

    def dependency(request: Request) -> None:
        if ENVIRONMENT == "test":
            return
        limiter.check(request)

    return dependency


enroll_limiter = make_limiter(name="enroll", limit=30, window=60)
heartbeat_limiter = make_limiter(name="heartbeat", limit=600, window=60)
ingest_limiter = make_limiter(name="ingest", limit=600, window=60)
