import math
import os
import secrets
import threading
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Header, HTTPException, Request


class RateLimiter:
    """In-memory rate limiter and lockout tracker."""

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


from dataclasses import dataclass

import jwt


@dataclass
class AdminUser:
    role: str
    plant_id: str | None = None
    user_id: str = ""


AdminRateLimiter = RateLimiter
admin_rate_limiter = RateLimiter(max_attempts=5, lockout_seconds=60.0)
viewer_rate_limiter = RateLimiter(max_attempts=5, lockout_seconds=60.0)


def get_client_ip(request: Request) -> str:
    """Extract client socket host IP strictly, without trusting X-Forwarded-For."""
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def _decode_clerk_jwt(token: str) -> dict[str, Any]:
    """
    Decodes and validates a Clerk session JWT using RS256.
    Fails closed if Clerk configuration is missing.
    Raises jwt.PyJWTError on invalid/expired tokens or unauthorized parties.
    """
    public_key_pem = os.getenv("CLERK_PEM_PUBLIC_KEY")
    jwks_url = os.getenv("CLERK_JWKS_URL")

    if not public_key_pem and not jwks_url:
        # Clerk auth is not configured; fail closed
        raise jwt.InvalidTokenError("Clerk authentication is not configured")

    expected_issuer = os.getenv("CLERK_ISSUER")
    authorized_parties_str = os.getenv("CLERK_AUTHORIZED_PARTIES", "")
    authorized_parties = [
        p.strip() for p in authorized_parties_str.split(",") if p.strip()
    ]

    key: Any = None
    if public_key_pem:
        key = public_key_pem.strip().replace("\\n", "\n")
    elif jwks_url:
        from jwt import PyJWKClient

        jwks_client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        key = signing_key.key

    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
        "leeway": 10,
        "options": {"verify_signature": True, "require": ["exp"]},
    }
    if expected_issuer:
        decode_kwargs["issuer"] = expected_issuer
        decode_kwargs["options"]["require"].append("iss")

    payload = jwt.decode(token, key, **decode_kwargs)

    if authorized_parties:
        token_azp = payload.get("azp")
        if not token_azp or token_azp not in authorized_parties:
            raise jwt.InvalidTokenError("Invalid azp claim")

    return payload


def verify_admin_user(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AdminUser:
    """
    Security dependency for admin endpoints enforcing authentication and lockout rate limiting.
    Evaluation order:
      (a) Lockout check first, before any credential comparison.
      (b) Static ADMIN_TOKEN compare (if set, authenticated as platform_admin).
      (c) Clerk JWT verify (RS256, exp, nbf, iss, azp).
      (d) A request that fails both counts as one failure in admin_rate_limiter.
      A valid static token or valid JWT does not count as a failure.
    """
    ip = get_client_ip(request)

    # (a) Lockout check first, before any comparison
    if admin_rate_limiter.is_locked_out(ip):
        retry_after = admin_rate_limiter.retry_after(ip)
        raise HTTPException(
            status_code=429,
            detail="Too many failed authentication attempts. Locked out.",
            headers={"Retry-After": str(retry_after)},
        )

    # Server configuration check: fail closed if no auth is configured
    admin_token = os.getenv("ADMIN_TOKEN")
    clerk_configured = bool(
        os.getenv("CLERK_PEM_PUBLIC_KEY") or os.getenv("CLERK_JWKS_URL")
    )
    if not admin_token and not clerk_configured:
        raise HTTPException(
            status_code=503,
            detail="Admin API disabled: ADMIN_TOKEN environment variable is not configured",
        )

    # Check header presence and Bearer format
    if not authorization or not authorization.startswith("Bearer "):
        admin_rate_limiter.record_failure(ip)
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Bearer token",
        )

    token = authorization[7:].strip()
    if not token:
        admin_rate_limiter.record_failure(ip)
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Bearer token",
        )

    # (b) Static ADMIN_TOKEN compare
    if admin_token and secrets.compare_digest(
        token.encode("utf-8"), admin_token.encode("utf-8")
    ):
        admin_rate_limiter.record_success(ip)
        return AdminUser(role="platform_admin", plant_id=None, user_id="static_admin")

    # (c) Clerk JWT verify
    try:
        payload = _decode_clerk_jwt(token)
    except (jwt.PyJWTError, ValueError):
        # Fails both static and Clerk verification
        admin_rate_limiter.record_failure(ip)
        raise HTTPException(
            status_code=401,
            detail="Invalid admin token",
        )

    # Token is cryptographically valid; clear failure history
    admin_rate_limiter.record_success(ip)

    # Inspect claims & role scoping
    meta = payload.get("metadata")
    if not isinstance(meta, dict):
        meta = payload.get("public_metadata")
    if not isinstance(meta, dict):
        meta = {}

    role = meta.get("role") or payload.get("role")
    plant_id = meta.get("plant_id") or payload.get("plant_id")
    user_id = payload.get("sub", "")

    if role not in ("platform_admin", "plant_manager"):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: User lacks administrative role",
        )

    if role == "plant_manager":
        if not plant_id or not isinstance(plant_id, str) or not plant_id.strip():
            raise HTTPException(
                status_code=403,
                detail="Forbidden: Plant manager missing or invalid plant_id claim",
            )
        plant_id = plant_id.strip()

    return AdminUser(role=role, plant_id=plant_id, user_id=user_id)


# Alias for backward compatibility
verify_admin_token = verify_admin_user


def require_platform_admin(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AdminUser:
    """Ensures caller has verified platform_admin privileges."""
    user = verify_admin_user(request, authorization)
    if user.role != "platform_admin":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Operation requires platform_admin role",
        )
    return user


def require_plant_access(plant_id: str, user: AdminUser) -> None:
    """Enforces plant manager scoping; platform_admin has access to all plants."""
    if user.role == "platform_admin":
        return
    if user.role == "plant_manager":
        if user.plant_id == plant_id:
            return
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden: Plant manager access denied for plant '{plant_id}'",
        )
    raise HTTPException(
        status_code=403,
        detail="Forbidden: Insufficient privileges",
    )
