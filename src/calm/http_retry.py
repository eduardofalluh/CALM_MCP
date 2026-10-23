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
  Otherwise the failure is raised with a message telling the agent to check
  whether the write was applied before retrying.
- Retries stop starting once ``DEADLINE`` seconds have passed, so a call can't
  hang the front end for minutes.

Failures are raised as RuntimeError with a readable message. Status responses
are returned unchanged so the callers' existing HTTP-error handling still runs.
"""

from __future__ import annotations

import logging
import time
from typing import Callable
from urllib.parse import urlparse

import requests
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError

log = logging.getLogger("calm-mcp.http")

ATTEMPTS = 3
BACKOFF = (1.0, 3.0)  # seconds before the 2nd and 3rd attempt
RETRY_STATUS = frozenset({502, 503, 504})
DEADLINE = 45.0
MAX_RETRY_AFTER = 10.0

_TRANSPORT_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# Indirection so tests can run without real sleeps.
_sleep = time.sleep
_clock = time.monotonic


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


def _delay(attempt: int, resp: requests.Response | None) -> float:
    delay = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
    if resp is not None:
        try:
            delay = min(float(resp.headers.get("Retry-After", delay)), MAX_RETRY_AFTER)
        except (TypeError, ValueError):
            pass
    return delay


def send(
    do_request: Callable[[], requests.Response],
    method: str,
    url: str,
    *,
    repeatable: bool,
) -> requests.Response:
    """Run ``do_request`` with the retry policy above and return its response."""
    start = _clock()
    path = urlparse(url).path or url
    attempt = 0
    while True:
        attempt += 1
        final = attempt >= ATTEMPTS or (_clock() - start) > DEADLINE
        try:
            resp = do_request()
        except _TRANSPORT_ERRORS as exc:
            nothing_sent = _never_connected(exc)
            if (repeatable or nothing_sent) and not final:
                log.warning("transient %s on %s %s (attempt %d) — retrying",
                            type(exc).__name__, method, path, attempt)
                _sleep(_delay(attempt, None))
                continue
            if repeatable or nothing_sent:
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
        if not final and (status == 429 or (repeatable and status in RETRY_STATUS)):
            log.warning("HTTP %d on %s %s (attempt %d) — retrying", status, method, path, attempt)
            _sleep(_delay(attempt, resp))
            continue
        return resp
