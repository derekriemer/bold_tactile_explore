"""Polite HTTP: User-Agent, minimum spacing between calls to a host, retry on busy servers."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx

from tactile_terrain import REPO_URL, __version__

USER_AGENT = f"tactile-terrain/{__version__} (+{REPO_URL})"
MIN_INTERVAL_S = 1.0
RETRY_STATUSES = {429, 502, 503, 504}
MAX_ATTEMPTS = 4
BACKOFF_S = 2.0
TIMEOUT_S = 120.0

SERVICES = {
    "overpass-api.de": "Overpass (the OpenStreetMap data service)",
    "nominatim.openstreetmap.org": "Nominatim (the OpenStreetMap place search)",
}

_last_call: dict[str, float] = {}


class DataServiceError(ValueError):
    """A free public data service did not answer. A ValueError so the server reports it as text."""


def _unreachable(host: str, reason: str) -> DataServiceError:
    service = SERVICES.get(host, host)
    return DataServiceError(
        f"{service} did not answer ({reason}). It is a free public service that needs no key "
        "or account, and it is sometimes overloaded or down for a few minutes. Nothing in your "
        "model was changed. Try again in a few minutes."
    )


def request(method: str, url: str, **kwargs) -> httpx.Response:
    host = urlparse(url).netloc
    headers = {"User-Agent": USER_AGENT} | kwargs.pop("headers", {})
    for attempt in range(MAX_ATTEMPTS):
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_call.get(host, float("-inf")))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()
        try:
            response = httpx.request(method, url, headers=headers, timeout=TIMEOUT_S, **kwargs)
        except httpx.TransportError as error:  # timeouts and connection failures
            if attempt == MAX_ATTEMPTS - 1:
                raise _unreachable(host, type(error).__name__) from error
            time.sleep(BACKOFF_S * 2**attempt)
            continue
        if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise _unreachable(host, f"HTTP {response.status_code}") from error
            return response
        retry_after = response.headers.get("Retry-After", "")
        time.sleep(float(retry_after) if retry_after.isdigit() else BACKOFF_S * 2**attempt)
    raise AssertionError("unreachable")
