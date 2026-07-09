from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import (
    API_RATE_LIMIT_REQUESTS,
    API_RATE_LIMIT_WINDOW_SECONDS,
    LOGIN_BACKOFF_BASE_SECONDS,
    LOGIN_BACKOFF_ENABLED,
    LOGIN_BACKOFF_FREE_FAILURES,
    LOGIN_BACKOFF_MAX_SECONDS,
    LOGIN_BACKOFF_RESET_SECONDS,
    LOGIN_RATE_LIMIT_REQUESTS,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_TRUST_PROXY_HEADERS,
    SUBSCRIPTION_RATE_LIMIT_REQUESTS,
    SUBSCRIPTION_RATE_LIMIT_WINDOW_SECONDS,
    XRAY_SUBSCRIPTION_PATH,
)


@dataclass
class _Window:
    reset_at: float
    count: int = 0


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int
    retry_after: int = 0


class FixedWindowRateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, _Window] = {}
        self._lock = Lock()

    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.time()
        with self._lock:
            window = self._windows.get(key)
            if window is None or now >= window.reset_at:
                window = _Window(reset_at=now + window_seconds)
                self._windows[key] = window

            reset_at = math.ceil(window.reset_at)
            if window.count >= limit:
                retry_after = max(1, math.ceil(window.reset_at - now))
                return RateLimitDecision(False, limit, 0, reset_at, retry_after)

            window.count += 1
            remaining = max(0, limit - window.count)
            return RateLimitDecision(True, limit, remaining, reset_at)


@dataclass
class _LoginFailures:
    count: int
    first_failed_at: float
    blocked_until: float = 0


class LoginBackoffLimiter:
    def __init__(self) -> None:
        self._failures: dict[str, _LoginFailures] = {}
        self._lock = Lock()

    def retry_after(self, key: str) -> int:
        if not LOGIN_BACKOFF_ENABLED:
            return 0
        now = time.time()
        with self._lock:
            state = self._failures.get(key)
            if state is None:
                return 0
            if now - state.first_failed_at > LOGIN_BACKOFF_RESET_SECONDS:
                self._failures.pop(key, None)
                return 0
            if state.blocked_until <= now:
                return 0
            return max(1, math.ceil(state.blocked_until - now))

    def record_failure(self, key: str) -> int:
        if not LOGIN_BACKOFF_ENABLED:
            return 0
        now = time.time()
        with self._lock:
            state = self._failures.get(key)
            if state is None or now - state.first_failed_at > LOGIN_BACKOFF_RESET_SECONDS:
                state = _LoginFailures(count=0, first_failed_at=now)
                self._failures[key] = state

            state.count += 1
            if state.count <= LOGIN_BACKOFF_FREE_FAILURES:
                return 0

            exponent = state.count - LOGIN_BACKOFF_FREE_FAILURES - 1
            delay = min(LOGIN_BACKOFF_MAX_SECONDS, LOGIN_BACKOFF_BASE_SECONDS * (2 ** exponent))
            state.blocked_until = now + delay
            return math.ceil(delay)

    def record_success(self, key: str) -> None:
        if not LOGIN_BACKOFF_ENABLED:
            return
        with self._lock:
            self._failures.pop(key, None)


fixed_window_limiter = FixedWindowRateLimiter()
login_backoff_limiter = LoginBackoffLimiter()


def get_client_ip(request: Request) -> str:
    if RATE_LIMIT_TRUST_PROXY_HEADERS:
        for header_name in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
            header = request.headers.get(header_name)
            if header:
                return header.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def login_backoff_key(client_ip: str, username: str) -> str:
    normalized_username = username.strip().lower()
    return f"{client_ip}:{normalized_username}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rule = _rule_for(request)
        if not RATE_LIMIT_ENABLED or rule is None:
            return await call_next(request)

        scope, limit, window_seconds = rule
        decision = fixed_window_limiter.check(
            _request_key(request, scope),
            limit=limit,
            window_seconds=window_seconds,
        )
        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers=_headers(decision),
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        response.headers["X-RateLimit-Reset"] = str(decision.reset_at)
        return response


def _rule_for(request: Request) -> tuple[str, int, int] | None:
    path = request.url.path.rstrip("/") or "/"
    subscription_prefix = f"/{XRAY_SUBSCRIPTION_PATH.strip('/')}"
    if path == "/api/admin/token":
        return "login", LOGIN_RATE_LIMIT_REQUESTS, LOGIN_RATE_LIMIT_WINDOW_SECONDS
    if path in {"/api/singbox/bootstrap.sh", "/api/singbox/nodes/enroll"}:
        return "singbox-enrollment", LOGIN_RATE_LIMIT_REQUESTS, LOGIN_RATE_LIMIT_WINDOW_SECONDS
    if subscription_prefix != "/" and (path == subscription_prefix or path.startswith(f"{subscription_prefix}/")):
        return "subscription", SUBSCRIPTION_RATE_LIMIT_REQUESTS, SUBSCRIPTION_RATE_LIMIT_WINDOW_SECONDS
    if path.startswith("/api/"):
        return "api", API_RATE_LIMIT_REQUESTS, API_RATE_LIMIT_WINDOW_SECONDS
    return None


def _request_key(request: Request, scope: str) -> str:
    if scope == "api":
        authorization = request.headers.get("authorization")
        if authorization:
            digest = hashlib.sha256(authorization.encode()).hexdigest()[:16]
            return f"{scope}:token:{digest}"
    if scope == "subscription":
        path_digest = hashlib.sha256(request.url.path.encode()).hexdigest()[:16]
        return f"{scope}:{get_client_ip(request)}:{path_digest}"
    return f"{scope}:{get_client_ip(request)}"


def _headers(decision: RateLimitDecision) -> dict[str, str]:
    return {
        "Retry-After": str(decision.retry_after),
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_at),
    }
