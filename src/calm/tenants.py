"""Several SAP Cloud ALM tenants behind one connection, picked per call with ``tenant``.

A Claude connector (or a GenAI Studio connection) is signed in to once, but a
person works on several customers' CALM: each conversation / project names the
one it means (``tenant="lutron"``). Each tenant is configured on the server only,
from env vars / secrets, never in code:

    CALM_TENANT_<NAME>_IDENTITY_ZONE   CALM_TENANT_<NAME>_REGION_ZONE
    CALM_TENANT_<NAME>_CLIENT_ID       CALM_TENANT_<NAME>_CLIENT_SECRET
    CALM_TENANT_<NAME>_ALLOWED_USERS   emails and / or @domains allowed to use it
    (optional CALM_TENANT_<NAME>_BASE_URL / _AUTH_URL, as CALM_BASE_URL / CALM_AUTH_URL)

The server opens a tenant with that tenant's own key, so on the shared HTTP
server it serves only a person whose SAP sign-in token it has verified itself
(signature against SAP's published keys, issuer, expiry) and who is on the
tenant's list; a tenant with no list serves nobody. A local (stdio) MCP is the
user's own machine and configuration, so it needs no sign-in.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass

import jwt
import requests

from . import http_retry
from .config import TenantNotConfiguredError, build_auth_url, build_base_url, get_auth_url

log = logging.getLogger("calm-mcp.tenants")

_ZONE_VAR = re.compile(r"^CALM_TENANT_([A-Z0-9_]+)_IDENTITY_ZONE$")
_KEYS_TTL = 3600.0
_REFETCH_AFTER = 60.0  # an unknown key id refetches SAP's keys at most once a minute
_KEYS: dict[str, tuple[float, dict]] = {}


@dataclass(frozen=True)
class Tenant:
    name: str
    identity_zone: str
    base_url: str
    auth_url: str
    client_id: str
    client_secret: str
    allowed: tuple[str, ...]
    missing: tuple[str, ...]  # env vars still to set before it can be used


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def configured() -> dict[str, Tenant]:
    """Every tenant with a CALM_TENANT_<NAME>_IDENTITY_ZONE, by lower-case name."""
    out: dict[str, Tenant] = {}
    for var, zone in sorted(os.environ.items()):
        m = _ZONE_VAR.match(var)
        if not m or not zone.strip():
            continue
        prefix = f"CALM_TENANT_{m.group(1)}_"

        def get(key: str) -> str:
            return os.getenv(prefix + key, "").strip()

        region = get("REGION_ZONE")
        # Never fill a missing region from the default tenant's: that would open another customer's CALM.
        base = get("BASE_URL") or (build_base_url(zone.strip(), region) if region else "")
        auth = get("AUTH_URL") or (build_auth_url(zone.strip(), region) if region else "")
        need = (("REGION_ZONE", base and auth), ("CLIENT_ID", get("CLIENT_ID")), ("CLIENT_SECRET", get("CLIENT_SECRET")))
        out[m.group(1).lower()] = Tenant(
            name=m.group(1).lower(), identity_zone=zone.strip(), base_url=base, auth_url=auth,
            client_id=get("CLIENT_ID"), client_secret=get("CLIENT_SECRET"),
            allowed=tuple(a.lower() for a in re.split(r"[\s,;]+", get("ALLOWED_USERS")) if a),
            missing=tuple(prefix + k for k, v in need if not v),
        )
    return out


def find(name: str, choices: list[Tenant]) -> Tenant | None:
    """The tenant called ``name`` (or with that identity zone), any case or spacing."""
    want = norm(name)
    return next((t for t in choices if want in (t.name, norm(t.identity_zone))), None)


def person_email(claims: dict) -> str:
    return str(claims.get("email") or claims.get("user_name") or "").strip().lower()


def allows(tenant: Tenant, claims: dict) -> bool:
    """Whether the verified person is on the tenant's list (an email, or their @domain)."""
    email = person_email(claims)
    return bool(email) and any(email == a or (a.startswith("@") and email.endswith(a)) for a in tenant.allowed)


def _issuers() -> dict[str, str]:
    """Token issuer → its SAP login, for every tenant this server knows (default + configured)."""
    auths = [t.auth_url for t in configured().values() if t.auth_url]
    try:
        auths.append(get_auth_url())
    except TenantNotConfiguredError:
        pass
    return {a: a[: -len("/oauth/token")] for a in auths if a.endswith("/oauth/token")}


def _fetch_jwks(base: str) -> dict:
    url = f"{base}/token_keys"
    resp = http_retry.send(lambda t: requests.get(url, headers={"Accept": "application/json"}, timeout=t),
                           "GET", url, repeatable=True, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _signing_key(base: str, kid: str | None):
    now = time.monotonic()
    fetched, keys = _KEYS.get(base, (None, {}))
    if fetched is None or now - fetched > _KEYS_TTL or (kid not in keys and now - fetched > _REFETCH_AFTER):
        try:
            keys = {k.get("kid"): jwt.PyJWK(k) for k in _fetch_jwks(base).get("keys", []) if k.get("kty") == "RSA"}
            _KEYS[base] = (now, keys)
        except Exception as exc:  # noqa: BLE001 — no keys: nobody is verified, nothing is opened
            log.warning("Could not read SAP's sign-in keys from %s: %s", base, exc)
    if kid in keys:
        return keys[kid]
    return next(iter(keys.values())) if kid is None and len(keys) == 1 else None


def verified_person(token: str | None) -> dict | None:
    """The claims of a person's SAP sign-in token, once this server has verified it
    came from a SAP login it knows (signature, issuer, expiry) — else None."""
    if not token:
        return None
    try:
        iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        return None
    base = _issuers().get(iss) if isinstance(iss, str) else None
    key = _signing_key(base, kid) if base else None
    if key is None:
        return None
    try:
        claims = jwt.decode(token, key.key, algorithms=["RS256"], issuer=iss, leeway=30,
                            options={"verify_aud": False, "require": ["exp", "iss"]})
    except jwt.PyJWTError:
        return None
    if claims.get("grant_type") in (None, "", "client_credentials") or not claims.get("user_name"):
        return None  # a key's token, not a person
    return claims
