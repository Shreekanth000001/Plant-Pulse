import math
import os
import secrets
import threading
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Header, HTTPException, Request


class AdminRateLimiter:
    """In-memory rate limiter and lockout tracker for admin endpoints."""

    def __init__(
        self,
        max_attempts: int = 5,
        lockout_seconds: float = 60.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._attempts: dict[str, dict[str, Any]] = {}

    def is_locked_out(self, ip: str) -> bool:
        with self._lock:
            now = self.clock()
            rec = self._attempts.get(ip)
            if not rec:
                return False
            if rec.get("locked_until", 0.0) > now:
                return True
            if (
                rec.get("locked_until", 0.0) <= now
                and rec.get("locked_until", 0.0) > 0.0
            ):
                del self._attempts[ip]
                return False
            return False

    def retry_after(self, ip: str) -> int:
        with self._lock:
            now = self.clock()
            rec = self._attempts.get(ip)
            if not rec:
                return int(self.lockout_seconds)
            locked_until = rec.get("locked_until", 0.0)
            remaining = math.ceil(locked_until - now)
            return max(remaining, 1)

    def record_failure(self, ip: str) -> None:
        with self._lock:
            now = self.clock()
            rec = self._attempts.setdefault(ip, {"count": 0, "locked_until": 0.0})
            rec["count"] += 1
            if rec["count"] >= self.max_attempts:
                rec["locked_until"] = now + self.lockout_seconds

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None)

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()


admin_rate_limiter = AdminRateLimiter(max_attempts=5, lockout_seconds=60.0)


def get_client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def verify_admin_token(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> None:
    """Security dependency for admin endpoints enforcing authentication and lockout rate limiting."""
    ip = get_client_ip(request)

    # 1. Lockout check runs before token comparison
    if admin_rate_limiter.is_locked_out(ip):
        retry_after = admin_rate_limiter.retry_after(ip)
        raise HTTPException(
            status_code=429,
            detail="Too many failed authentication attempts. Locked out.",
            headers={"Retry-After": str(retry_after)},
        )

    # 2. Server configuration check
    admin_token = os.getenv("ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(
            status_code=503,
            detail="Admin API disabled: ADMIN_TOKEN environment variable is not configured",
        )

    # 3. Header presence and format validation
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Bearer token",
        )

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Bearer token",
        )

    # 4. Constant-time token verification
    if not secrets.compare_digest(token.encode("utf-8"), admin_token.encode("utf-8")):
        admin_rate_limiter.record_failure(ip)
        raise HTTPException(
            status_code=401,
            detail="Invalid admin token",
        )

    # 5. Success clears prior failed attempts
    admin_rate_limiter.record_success(ip)
