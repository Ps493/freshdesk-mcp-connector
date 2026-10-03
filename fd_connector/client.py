"""Hardened, read-only Freshdesk HTTP client (stdlib only).

Guarantees: GET-only, no redirects (never leaks the API key), client-side token bucket,
Retry-After-aware 429 handling, jittered backoff on 5xx/network errors, typed errors.
"""
from __future__ import annotations
import base64, json, random, re, sys, threading, time
import urllib.error, urllib.parse, urllib.request
from typing import Any, Callable

DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MAX_RETRY_WAIT = 60.0


class FreshdeskError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after

    def to_dict(self) -> dict:
        d = {"status": self.status, "code": self.code, "message": self.message}
        if self.retry_after:
            d["retry_after_seconds"] = self.retry_after
        return d


class TokenBucket:
    """Proactive limiter so we stay under the plan's per-minute quota instead of hitting 429s."""
    def __init__(self, per_minute: int, clock=time.monotonic, sleep=time.sleep, burst: int | None = None):
        # burst + per_minute must stay <= the plan quota so any fixed 60s window is safe
        self.capacity = burst or per_minute
        self.tokens, self.rate = float(self.capacity), per_minute / 60.0
        self.clock, self.sleep, self.last, self.lock = clock, sleep, clock(), threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = self.clock()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            self.sleep(wait)


    def sync(self, total, remaining) -> None:
        """Adopt the server's authoritative view; other processes may share this API key."""
        with self.lock:
            if total and total > 0:
                self.capacity = min(self.capacity, total)
                self.rate = min(self.rate, total / 60.0)
            if remaining is not None:
                self.tokens = min(self.tokens, max(float(remaining), 0.0))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # surface 3xx as an error rather than follow with credentials
        return None


def _log(msg: str) -> None:
    print(f"[fd-connector] {msg}", file=sys.stderr, flush=True)  # never log headers/keys


class FreshdeskClient:
    def __init__(self, domain: str, api_key: str, *, base_url: str | None = None,
                 calls_per_minute: int = 40, burst: int = 10, max_retries: int = 4, timeout: float = 15.0,
                 sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise ValueError("FRESHDESK_API_KEY is required")
        if base_url:  # test hook; https required unless loopback
            u = urllib.parse.urlparse(base_url)
            if u.scheme != "https" and u.hostname not in ("127.0.0.1", "localhost"):
                raise ValueError("base_url must be https (or loopback for tests)")
            self.base_url = base_url.rstrip("/")
        else:
            if not DOMAIN_RE.match(domain or ""):
                raise ValueError("FRESHDESK_DOMAIN must be the subdomain only, e.g. 'acme' for acme.freshdesk.com")
            self.base_url = f"https://{domain}.freshdesk.com"
        token = base64.b64encode(f"{api_key}:X".encode()).decode()
        self._auth = f"Basic {token}"
        self.max_retries, self.timeout, self.sleep = max_retries, timeout, sleep
        self.bucket = TokenBucket(calls_per_minute, sleep=sleep, burst=burst)
        self.opener = urllib.request.build_opener(_NoRedirect)
        self.last_rate: dict[str, Any] = {}

    def get(self, path: str, params: dict | None = None) -> tuple[Any, dict]:
        url = f"{self.base_url}/api/v2{path}"
        if params:
            q = {k: v for k, v in params.items() if v is not None}
            url += "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)
        for attempt in range(self.max_retries + 1):
            self.bucket.acquire()
            req = urllib.request.Request(url, method="GET", headers={
                "Authorization": self._auth, "Accept": "application/json", "User-Agent": "fd-agent-connector/1.0"})
            try:
                with self.opener.open(req, timeout=self.timeout) as r:
                    hdrs = {k.lower(): v for k, v in r.headers.items()}
                    self._track(hdrs)
                    raw = r.read()
                    return (json.loads(raw) if raw else None), hdrs
            except urllib.error.HTTPError as e:
                hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
                self._track(hdrs)
                body = e.read().decode("utf-8", "replace")[:500]
                last = attempt == self.max_retries
                if e.code == 429:
                    wait = min(float(hdrs.get("retry-after", 0) or 0) or self._backoff(attempt), MAX_RETRY_WAIT)
                    if last:
                        raise FreshdeskError(429, "rate_limited", "Freshdesk rate limit exhausted after retries", wait)
                    _log(f"429 on {path}; sleeping {wait:.1f}s (attempt {attempt + 1})")
                    self.sleep(wait)
                    continue
                if e.code >= 500 and not last:
                    self.sleep(self._backoff(attempt))
                    continue
                raise self._map(e.code, body)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.max_retries:
                    raise FreshdeskError(0, "network_error", f"Network failure: {type(e).__name__}")
                self.sleep(self._backoff(attempt))
        raise FreshdeskError(0, "unreachable", "retry loop exited")

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2 ** attempt, 30) * (0.5 + random.random() / 2)

    def _track(self, h: dict) -> None:
        for k in ("x-ratelimit-total", "x-ratelimit-remaining", "x-ratelimit-used-currentrequest"):
            if k in h:
                self.last_rate[k.replace("x-ratelimit-", "")] = h[k]
        try:
            self.bucket.sync(int(float(h["x-ratelimit-total"])), int(float(h["x-ratelimit-remaining"])))  # live API sends "47.0"
        except (KeyError, ValueError):
            pass

    @staticmethod
    def _map(status: int, body: str) -> FreshdeskError:
        msg = body
        try:
            j = json.loads(body)
            msg = j.get("description") or j.get("message") or body
        except Exception:
            pass
        table = {401: ("auth_failed", "Invalid API key or domain"), 403: ("forbidden", "Key lacks permission for this resource"),
                 404: ("not_found", "Resource not found"), 400: ("invalid_request", msg), 422: ("invalid_request", msg)}
        code, m = table.get(status, ("upstream_error", f"Freshdesk returned HTTP {status}"))
        return FreshdeskError(status, code, m)

    @staticmethod
    def has_next(headers: dict) -> bool:
        return 'rel="next"' in headers.get("link", "")
