"""
SAP XSUAA client-credentials token manager.

Flow
----
1. POST to the XSUAA token URL with Basic Auth (Base64 client_id:client_secret)
   and grant_type=client_credentials.
2. Cache the returned access token until ~60 s before it expires.
3. Any thread that calls get_managed_token() gets a valid token transparently —
   no manual copy-paste, no hourly interruptions.

Two separate URLs are involved:
  Auth  → https://<tenant>.authentication.<region>.hana.ondemand.com/oauth/token
  API   → https://<tenant>.<region>.alm.cloud.sap/api/...

Per-tenant cache
----------------
get_or_create_token_manager(client_id, client_secret, auth_url) returns a cached
TokenManager keyed by (client_id, auth_url), creating one on first use.  This
lets a single server process serve multiple tenants when credentials arrive via
request headers rather than server env vars.
"""

from __future__ import annotations

import base64
import threading
import time

import requests

from .config import build_auth_url

_REFRESH_BUFFER_SECONDS = 60  # refresh this many seconds before expiry


class TokenManager:
    """Thread-safe SAP XSUAA client-credentials token cache."""

    def __init__(self, client_id: str, client_secret: str, auth_url: str | None = None) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._auth_url = auth_url or build_auth_url()
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def get_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires_at - _REFRESH_BUFFER_SECONDS:
                return self._token
            self._refresh()
            return self._token  # type: ignore[return-value]

    def _refresh(self) -> None:
        raw = f"{self._client_id}:{self._client_secret}".encode()
        basic = base64.b64encode(raw).decode()

        # grant_type goes in the x-www-form-urlencoded body (OAuth2 standard;
        # matches `curl -u id:secret -d grant_type=client_credentials`). Some
        # XSUAA configs 401 when it's only a query param with no request body.
        resp = requests.post(
            self._auth_url,
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {basic}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            # Surface XSUAA's actual message (never the secret) to aid debugging.
            raise RuntimeError(
                f"XSUAA token request failed: HTTP {resp.status_code} {resp.reason} "
                f"at {self._auth_url} — response: {resp.text[:500]}"
            )
        data = resp.json()

        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600))


# ---------------------------------------------------------------------------
# Module-level singleton — initialised once at server startup (env-var mode)
# ---------------------------------------------------------------------------

_manager: TokenManager | None = None


def init_token_manager(client_id: str, client_secret: str, auth_url: str | None = None) -> None:
    global _manager
    _manager = TokenManager(client_id=client_id, client_secret=client_secret, auth_url=auth_url)


def get_managed_token() -> str | None:
    return _manager.get_token() if _manager else None


# ---------------------------------------------------------------------------
# Per-tenant cache — used when credentials arrive via request headers
# ---------------------------------------------------------------------------

_tenant_managers: dict[tuple[str, str], TokenManager] = {}
_tenant_lock = threading.Lock()


def get_or_create_token_manager(client_id: str, client_secret: str, auth_url: str) -> TokenManager:
    """Return a cached TokenManager for (client_id, auth_url), creating one if needed."""
    key = (client_id, auth_url)
    with _tenant_lock:
        if key not in _tenant_managers:
            _tenant_managers[key] = TokenManager(
                client_id=client_id, client_secret=client_secret, auth_url=auth_url
            )
        return _tenant_managers[key]
