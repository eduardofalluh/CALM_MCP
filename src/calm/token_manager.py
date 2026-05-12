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

        resp = requests.post(
            self._auth_url,
            params={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600))


# ---------------------------------------------------------------------------
# Module-level singleton — initialised once at server startup
# ---------------------------------------------------------------------------

_manager: TokenManager | None = None


def init_token_manager(client_id: str, client_secret: str, auth_url: str | None = None) -> None:
    global _manager
    _manager = TokenManager(client_id=client_id, client_secret=client_secret, auth_url=auth_url)


def get_managed_token() -> str | None:
    return _manager.get_token() if _manager else None
