"""Bounded retries for transient HTTP failures, shared by every outbound call.

SAP's gateway occasionally drops a connection without replying
("Remote end closed connection without response"), times out, or answers
502/503/504/429 under load. Without handling, one such blip surfaces to the
user as a raw Python exception and the whole agent step fails.

Policy:
- Repeatable requests (GETs, the client-credentials token POST) are retried up
  to ``ATTEMPTS`` times with a short backoff on a dropped connection, a timeout,
  or HTTP 502/503/504/429.
- Writes are NOT repeated once the request may have reached SAP: a second POST
  could create a duplicate. They are retried only when the connection was never
  established (nothing was sent) or on HTTP 429 (rejected before processing).
  A dropped connection or a 502/503/504 gateway answer on a write is raised with
  a message telling the agent to check whether the write was applied before
  retrying.
- TLS / certificate failures are never retried: they are configuration
  problems (trust store, TLS-inspecting proxy), not blips.
- The whole call stays within ``DEADLINE`` seconds after its first attempt: a
  retry only starts if there is time left for it, and its timeout is cut to fit.
- Optional lookups run inside ``best_effort()``: one attempt, short timeout.

Failures are raised as RuntimeError with a readable message. Other status
responses are returned unchanged so the callers' HTTP-error handling still runs.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import math
import re
import time
from typing import Callable, Iterator
from urllib.parse import urlparse

import requests
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError

log = logging.getLogger("calm-mcp.http")

ATTEMPTS = 3
BACKOFF = (1.0, 3.0)  # seconds before the 2nd and 3rd attempt
RETRY_STATUS = frozenset({502, 503, 504})
DEADLINE = 45.0
MIN_ATTEMPT = 5.0  # don't start a retry with less time than this left
MAX_RETRY_AFTER = 10.0
BEST_EFFORT_TIMEOUT = 10.0

_TRANSPORT_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# Indirection so tests can run without real sleeps.
_sleep = time.sleep
_clock = time.monotonic

# (attempts, max timeout) for calls inside best_effort(); None = normal policy.
_budget: contextvars.ContextVar[tuple[int, float] | None] = contextvars.ContextVar(
    "calm_http_budget", default=None
)


@contextlib.contextmanager
def best_effort(timeout: float = BEST_EFFORT_TIMEOUT) -> Iterator[None]:
    """One attempt with a short timeout, for optional lookups (e.g. display
    names) that must never hold up the answer they decorate."""
    token = _budget.set((1, timeout))
    try:
        yield
    finally:
        _budget.reset(token)


def _never_connected(exc: Exception) -> bool:
    """True when the request certainly never left this process."""
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return True
    inner = exc.args[0] if exc.args else None
    reason = getattr(inner, "reason", inner)
    return isinstance(reason, (NewConnectionError, ConnectTimeoutError))


def _reason(exc: Exception) -> str:
    text = repr(exc)
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "could not connect (connect timeout)"
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "no response before the request timed out"
    if "RemoteDisconnected" in text:
        return "SAP closed the connection without a response"
    if "ConnectionResetError" in text or "Connection reset" in text:
        return "the connection was reset"
    if _never_connected(exc):
        return "could not connect"
    return type(exc).__name__


def _tls_reason(exc: Exception) -> str:
    match = re.search(r"certificate verify failed: ([^)'\"]+)", repr(exc))
    return f"certificate verify failed: {match.group(1).strip()}" if match else type(exc).__name__


def _delay(attempt: int, resp: requests.Response | None) -> float:
    delay = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
    if resp is not None:
        try:
            asked = float(resp.headers.get("Retry-After", delay))
        except (TypeError, ValueError):
            asked = delay  # an HTTP-date or junk: keep the default backoff
        if math.isfinite(asked) and asked >= 0:
            delay = min(asked, MAX_RETRY_AFTER)
    return delay


def send(
    do_request: Callable[[float], requests.Response],
    method: str,
    url: str,
    *,
    repeatable: bool,
    timeout: float,
) -> requests.Response:
    """Run ``do_request(timeout)`` under the policy above and return its response."""
    override = _budget.get()
    attempts, timeout = (override[0], min(timeout, override[1])) if override else (ATTEMPTS, timeout)
    start = _clock()
    path = urlparse(url).path or url
    attempt = 0
    this_timeout = timeout

    def next_timeout(resp: requests.Response | None) -> float | None:
        """Sleep and return the next attempt's timeout, or None to stop."""
        if attempt >= attempts:
            return None
        delay = _delay(attempt, resp)
        left = DEADLINE - (_clock() - start) - delay
        if left < MIN_ATTEMPT:
            return None
        _sleep(delay)
        return min(timeout, left)

    while True:
        attempt += 1
        try:
            resp = do_request(this_timeout)
        except requests.exceptions.SSLError as exc:
            raise RuntimeError(
                f"TLS error talking to SAP Cloud ALM on {method} {path}: {_tls_reason(exc)}. "
                "This is a configuration problem, not a temporary one: check the server's "
                "CA trust store (certifi / REQUESTS_CA_BUNDLE) and any TLS-inspecting proxy."
            ) from exc
        except _TRANSPORT_ERRORS as exc:
            nothing_sent = _never_connected(exc)
            if repeatable or nothing_sent:
                nxt = next_timeout(None)
                if nxt is not None:
                    log.warning("transient %s on %s %s (attempt %d) — retrying",
                                type(exc).__name__, method, path, attempt)
                    this_timeout = nxt
                    continue
                msg = (
                    f"SAP Cloud ALM did not respond to {method} {path}: {_reason(exc)} "
                    f"(tried {attempt} times). This is a temporary network or SAP-side "
                    "problem and nothing was changed — try again in a moment."
                )
            else:
                msg = (
                    f"SAP Cloud ALM did not confirm {method} {path}: {_reason(exc)}. The "
                    "change may or may not have been applied. Before retrying, read the "
                    "item back (e.g. list or search for its title) so no duplicate is "
                    "created."
                )
            raise RuntimeError(msg) from exc

        status = resp.status_code
        if status == 429 or (repeatable and status in RETRY_STATUS):
            nxt = next_timeout(resp)
            if nxt is not None:
                log.warning("HTTP %d on %s %s (attempt %d) — retrying", status, method, path, attempt)
                this_timeout = nxt
                continue
            return resp
        if not repeatable and status in RETRY_STATUS:
            raise RuntimeError(
                f"SAP Cloud ALM answered {method} {path} with HTTP {status} (a gateway error). "
                "The change may or may not have been applied. Before retrying, read the item "
                "back (e.g. list or search for its title) so no duplicate is created."
            )
        return resp
