"""Polite HTTP: User-Agent, minimum spacing between calls to a host, retry on 429 and 504."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx

from tactile_terrain import REPO_URL, __version__

USER_AGENT = f"tactile-terrain/{__version__} (+{REPO_URL})"
MIN_INTERVAL_S = 1.0
RETRY_STATUSES = {429, 504}
MAX_ATTEMPTS = 4
BACKOFF_S = 2.0
TIMEOUT_S = 120.0

_last_call: dict[str, float] = {}


def request(method: str, url: str, **kwargs) -> httpx.Response:
    host = urlparse(url).netloc
    headers = {"User-Agent": USER_AGENT} | kwargs.pop("headers", {})
    for attempt in range(MAX_ATTEMPTS):
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_call.get(host, float("-inf")))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()
        response = httpx.request(method, url, headers=headers, timeout=TIMEOUT_S, **kwargs)
        if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("Retry-After", "")
        time.sleep(float(retry_after) if retry_after.isdigit() else BACKOFF_S * 2**attempt)
    raise AssertionError("unreachable")
