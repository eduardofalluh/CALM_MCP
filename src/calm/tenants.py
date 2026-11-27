"""Several SAP Cloud ALM tenants behind one connection, picked per call with ``tenant``.

A Claude connector (or a GenAI Studio connection) is signed in to once, but a
person works on several customers' CALM: each conversation / project names the
one it means (``tenant="lutron"``). Each tenant is configured on the server only,
from env vars / secrets, never in code:

    CALM_TENANT_<NAME>_IDENTITY_ZONE   CALM_TENANT_<NAME>_REGION_ZONE
    CALM_TENANT_<NAME>_CLIENT_ID       CALM_TENANT_<NAME>_CLIENT_SECRET
    CALM_TENANT_<NAME>_ALLOWED_USERS   emails and / or @domains allowed to use it
    (optional CALM_TENANT_<NAME>_BASE_URL / _AUTH_URL, as CALM_BASE_URL / CALM_AUTH_URL)

or added by an admin from a chat (tenant_store.py, tools/admin.py); a name set on the
server wins over the same name added from a chat.

The server opens a tenant with that tenant's own key, so on the shared HTTP
server it serves only a person whose SAP sign-in token it has verified itself
(signature against SAP's published keys, issuer, expiry) and who is on the
tenant's list; a tenant with no list serves nobody. A local (stdio) MCP is the
user's own machine and configuration, so it needs no sign-in.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass

import jwt
import requests

from . import http_retry, tenant_store
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


def _tenant(name: str, zone: str, region: str, client_id: str, secret: str, allowed, base: str, auth: str,
            label: str) -> Tenant:
    # Never fill a missing region from the default tenant's: that would open another customer's CALM.
    base = base or (build_base_url(zone, region) if region else "")
    auth = auth or (build_auth_url(zone, region) if region else "")
    need = (("REGION_ZONE", base and auth), ("CLIENT_ID", client_id), ("CLIENT_SECRET", secret))
    return Tenant(name=name, identity_zone=zone, base_url=base, auth_url=auth, client_id=client_id,
                  client_secret=secret, allowed=tuple(str(a).lower() for a in allowed if a),
                  missing=tuple(label + k for k, v in need if not v))


def configured() -> dict[str, Tenant]:
    """Every tenant, by lower-case name: CALM_TENANT_<NAME>_IDENTITY_ZONE ones, then those added from a chat."""
    out: dict[str, Tenant] = {}
    for var, zone in sorted(os.environ.items()):
        m = _ZONE_VAR.match(var)
        if not m or not zone.strip():
            continue
        prefix = f"CALM_TENANT_{m.group(1)}_"

        def get(key: str) -> str:
            return os.getenv(prefix + key, "").strip()

        out[m.group(1).lower()] = _tenant(
            m.group(1).lower(), zone.strip(), get("REGION_ZONE"), get("CLIENT_ID"), get("CLIENT_SECRET"),
            re.split(r"[\s,;]+", get("ALLOWED_USERS")), get("BASE_URL"), get("AUTH_URL"), prefix)
    for name, c in tenant_store.stored_tenants().items():
        if name not in out:
            out[name] = _tenant(name, c["identity_zone"], c["region_zone"], c["client_id"], c["client_secret"],
                                c.get("allowed", []), "", "", f"client {name}: ")
    return out


def default_name() -> str:
    """What people call the connection's own SAP Cloud ALM when they pick it (CALM_DEFAULT_TENANT_NAME)."""
    return norm(os.getenv("CALM_DEFAULT_TENANT_NAME", "")) or "default"


def is_default(name: str) -> bool:
    return norm(name) in ("default", default_name())


def server_names() -> set[str]:
    """Tenants set on the server itself (env), which only the deployment changes."""
    return {m.group(1).lower() for var, zone in os.environ.items() if (m := _ZONE_VAR.match(var)) and zone.strip()}


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


def signin() -> dict | None:
    """The connector's own sign-in on SAP BTP: the XSUAA instance named in CALM_SIGNIN_INSTANCE,
    bound to this Cloud Foundry app (VCAP_SERVICES), found by exact name, never by scanning.
    Its tokens are the only way in, and only with its one scope ("<xsappname>.Claude")."""
    name = os.getenv("CALM_SIGNIN_INSTANCE", "").strip()
    if not name:
        return None
    try:
        services = json.loads(os.getenv("VCAP_SERVICES") or "{}")
    except ValueError:
        services = {}
    found = [s for group in services.values() if isinstance(group, list)
             for s in group if isinstance(s, dict) and s.get("name") == name]
    if len(found) != 1:
        raise RuntimeError(f"CALM_SIGNIN_INSTANCE is {name}, but that service instance is "
                           f"{'not bound to this app' if not found else 'bound more than once'}.")
    c = found[0].get("credentials") or {}
    url, xsappname, clientid = str(c.get("url") or "").rstrip("/"), c.get("xsappname"), c.get("clientid")
    if not (url.startswith("https://") and xsappname and clientid):
        raise RuntimeError(f"The binding of {name} has no url / xsappname / clientid: is it an XSUAA instance?")
    return {"url": url, "issuer": f"{url}/oauth/token", "xsappname": xsappname, "clientid": clientid,
            "scope": f"{xsappname}.Claude"}


def _issuers() -> dict[str, str]:
    """Token issuer → its SAP login, for every tenant this server knows (default + configured)
    and the connector's own sign-in."""
    auths = [t.auth_url for t in configured().values() if t.auth_url]
    own = signin()
    if own:
        auths.append(own["issuer"])
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


def verified_person(token: str | None, require_role: bool = True) -> dict | None:
    """The claims of a person's SAP sign-in token, once this server has verified it
    came from a SAP login it knows (signature, issuer, expiry) — else None. A token from the
    connector's own sign-in must also be meant for it (audience) and, unless require_role is
    False, carry its scope (the person was given the connector's role collection)."""
    if not token:
        return None
    try:
        iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        return None
    own = signin()
    if own and iss != own["issuer"]:
        return None  # on the Claude connector only its own sign-in says who someone is, never a client's login
    base = _issuers().get(iss) if isinstance(iss, str) else None
    key = _signing_key(base, kid) if base else None
    if key is None:
        return None
    mine = bool(own) and iss == own["issuer"]
    try:
        claims = jwt.decode(token, key.key, algorithms=["RS256"], issuer=iss, leeway=30,
                            audience=[own["xsappname"], own["clientid"]] if mine else None,
                            options={"verify_aud": mine, "require": ["exp", "iss"]})
    except jwt.PyJWTError:
        return None
    if mine and require_role and own["scope"] not in (claims.get("scope") or []):
        return None
    if claims.get("grant_type") in (None, "", "client_credentials") or not claims.get("user_name"):
        return None  # a key's token, not a person
    return claims
