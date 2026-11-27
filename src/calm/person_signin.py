"""Each person signs in to a client's own SAP login (a tenant with ALLOWED_USERS=signin).

No list of people is kept for such a client: its SAP decides. The first time someone opens it,
the tool answers with a link (dependencies.SignInNeeded). The link opens the client's SAP sign-in
in their browser, with their own account there, as in CALM itself. This server then keeps that
sign-in, encrypted, for that person and that client only, and renews it until SAP stops. No
account, or no SAP Cloud ALM API permission there: access not granted, nothing kept. CALM then
records the person, not "API".

The client's BTP admin allows it once: their CALM API key gets this server's return address
(https://<mcp address without /mcp>/signin/callback) and the authorization-code grant.

Sign-ins are kept in the client store (CALM_TENANT_STORE) when there is one, which every copy of
the MCP shares; otherwise in this process only, so people sign in again after a restart and the
app must run as one instance.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import jwt
import requests
from cryptography.fernet import Fernet, InvalidToken

from . import http_retry, tenant_store, tenants

log = logging.getLogger("calm-mcp.signin")
audit_log = logging.getLogger("calm-mcp.audit")

LINK_TTL = 600  # a sign-in link works for 10 minutes
_STATE_TTL = 900  # time to finish SAP's sign-in once it is started
_MEMORY: dict[str, dict] = {}  # the sign-ins, when there is no client store
_PROCESS_KEY = Fernet.generate_key()
_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'"}


def _box() -> Fernet:
    """Seals links and sign-ins in progress: a key derived from the client store's, so any copy of the
    MCP opens them; else this process's own."""
    if tenant_store.not_ready():
        return Fernet(_PROCESS_KEY)
    derived = hashlib.sha256(b"calm-person-signin|" + os.environ["CALM_TENANT_STORE_KEY"].strip().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _key(claims: dict, tenant: str) -> str:
    """One person (as the connector's sign-in names them) at one client."""
    who = claims.get("user_id") or claims.get("sub") or claims.get("user_name")
    return hashlib.sha256(f"{claims.get('iss')}|{who}|{tenant}".encode()).hexdigest()


def _get(key: str) -> dict | None:
    return (_MEMORY if tenant_store.not_ready() else tenant_store.load().get("signins", {})).get(key)


def _put(key: str, record: dict | None) -> None:
    """Keep a sign-in, or forget it (None)."""
    if tenant_store.not_ready():
        _MEMORY.pop(key, None) if record is None else _MEMORY.__setitem__(key, record)
        return
    data = tenant_store.load()
    signins = data.setdefault("signins", {})
    if record is None and key not in signins:
        return
    signins.pop(key, None) if record is None else signins.__setitem__(key, record)
    tenant_store.save(data)


def _token_request(tenant: tenants.Tenant, form: dict) -> dict:
    """A call to the client's SAP login with its CALM API key (SAP needs the key to finish a sign-in)."""
    basic = base64.b64encode(f"{tenant.client_id}:{tenant.client_secret}".encode()).decode()
    resp = http_retry.send(
        lambda t: requests.post(tenant.auth_url, data=form, timeout=t,
                                headers={"Authorization": f"Basic {basic}", "Accept": "application/json"}),
        "POST", tenant.auth_url, repeatable=True, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _record(tenant: tenants.Tenant, data: dict, account: str, refresh: str | None = None) -> dict:
    return {"tenant": tenant.name, "auth_url": tenant.auth_url, "access": data["access_token"],
            "refresh": data.get("refresh_token") or refresh, "account": account,
            "expires": time.time() + int(data.get("expires_in", 3600))}


def token_for(claims: dict, tenant: tenants.Tenant) -> str | None:
    """This person's own token for the client, renewed when it has run out; None when they must sign in."""
    key = _key(claims, tenant.name)
    rec = _get(key)
    if not rec or rec.get("auth_url") != tenant.auth_url:  # never a sign-in made for another address
        return None
    if rec["expires"] > time.time() + 60:
        return rec["access"]
    if rec.get("refresh"):
        try:
            rec = _record(tenant, _token_request(tenant, {"grant_type": "refresh_token",
                                                         "refresh_token": rec["refresh"]}),
                          rec.get("account", ""), rec["refresh"])
            _put(key, rec)
            return rec["access"]
        except Exception as exc:  # noqa: BLE001 — SAP stopped renewing it: the person signs in again
            log.info("Renewing a sign-in to %s failed; the person signs in again: %s", tenant.name, str(exc)[:200])
    _put(key, None)
    return None


def link(mcp_base: str, claims: dict, tenant: tenants.Tenant) -> str:
    """A link only this person can complete (sealed: their identity, the client, the return address)."""
    sealed = _box().encrypt(json.dumps({
        "k": "link", "p": _key(claims, tenant.name), "e": tenants.person_email(claims), "t": tenant.name,
        "r": f"{mcp_base}/signin/callback"}).encode()).decode()
    return f"{mcp_base}/signin/start/{sealed}"


def _open(sealed: str, kind: str, ttl: int) -> dict | None:
    try:
        data = json.loads(_box().decrypt(sealed.encode(), ttl=ttl))
    except (InvalidToken, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("k") == kind else None


def _tenant(name: str) -> tenants.Tenant | None:
    t = tenants.configured().get(name)
    return t if t and t.signin and not t.missing and t.auth_url.endswith("/oauth/token") else None


def _page(title: str, *lines: str, action: tuple[str, str] | None = None) -> str:
    body = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
    if action:
        body += f'<p><a href="{html.escape(action[0])}">{html.escape(action[1])}</a></p>'
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title></head>"
            f"<body><h1>{html.escape(title)}</h1>{body}</body></html>")


def _audit(link_data: dict, tenant: str, outcome: str) -> None:
    audit_log.info("AUDIT user=%s tenant=%s tool=signin outcome=%s", link_data.get("e") or "?", tenant, outcome)


def start_page(sealed: str) -> tuple[int, str]:
    """The link's page: says whose connector it signs in, then sends the person to the client's SAP login."""
    d = _open(sealed, "link", LINK_TTL)
    t = _tenant(d["t"]) if d else None
    if d is None or t is None:
        return 400, _page("This sign-in link doesn't work any more",
                          f"Each link works for {LINK_TTL // 60} minutes. Ask Claude again for a new one.")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = _box().encrypt(json.dumps({**d, "k": "state", "v": verifier}).encode()).decode()
    url = t.auth_url.removesuffix("/token") + "/authorize?" + urlencode({
        "response_type": "code", "client_id": t.client_id, "redirect_uri": d["r"], "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    return 200, _page(f"Sign in to {t.name}'s SAP Cloud ALM",
                      f"This connects your own {t.name} SAP login to the SAP Cloud ALM connector of {d['e']}. "
                      "Continue only if that is you.", action=(url, f"Continue to {t.name}'s SAP sign-in"))


def callback_page(params: dict) -> tuple[int, str]:
    """Where the client's SAP login sends the person back: keep the sign-in, or say access is not granted."""
    d = _open(str(params.get("state") or ""), "state", _STATE_TTL)
    t = _tenant(d["t"]) if d else None
    if d is None or t is None:
        return 400, _page("This sign-in has expired", "Ask Claude again for a new link.")
    if params.get("error") or not params.get("code"):
        _audit(d, t.name, "refused by SAP")
        said = str(params.get("error_description") or params.get("error") or "")[:300]
        return 403, _page("Access not granted", f"{t.name}'s SAP login didn't sign you in{': ' + said if said else ''}.",
                          f"You don't have access to {t.name}'s SAP Cloud ALM, or the sign-in was cancelled.")
    try:
        data = _token_request(t, {"grant_type": "authorization_code", "code": params["code"],
                                  "redirect_uri": d["r"], "code_verifier": d["v"]})
        # Straight from the client's SAP login over TLS, with its key: read, not verified again.
        claims = jwt.decode(data["access_token"], options={"verify_signature": False})
    except Exception as exc:  # noqa: BLE001 — SAP's answer goes back to the person
        log.warning("Finishing a sign-in to %s failed: %s", t.name, str(exc)[:300])
        return 502, _page("Not signed in", f"{t.name}'s SAP login didn't finish the sign-in. Ask Claude for a new "
                          f"link and try again. SAP said: {str(exc)[:200]}")
    account = tenants.person_email(claims) or str(claims.get("user_name") or "")
    if (claims.get("grant_type") in (None, "", "client_credentials")
            or not any("calm-api." in str(s) for s in claims.get("scope") or [])):
        _audit(d, t.name, "no CALM API permission")
        return 403, _page("Access not granted",
                          f"You signed in to {t.name}'s SAP as {account}, but that account has no SAP Cloud ALM API "
                          f"permission there, so you don't have access to {t.name}'s SAP Cloud ALM through Claude.",
                          f"Ask {t.name}'s SAP Cloud ALM administrator for access, then ask Claude for a new link.")
    _put(d["p"], _record(t, data, account))
    _audit(d, t.name, "signed in")
    return 200, _page(f"Signed in to {t.name}'s SAP Cloud ALM",
                      f"You are signed in as {account}. Go back to Claude and say you're done.")


def register(mcp) -> None:
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import HTMLResponse

    @mcp.custom_route("/signin/start/{sealed}", methods=["GET"])
    async def signin_start(request) -> HTMLResponse:
        status, page = await run_in_threadpool(start_page, request.path_params["sealed"])
        return HTMLResponse(page, status_code=status, headers=_HEADERS)

    @mcp.custom_route("/signin/callback", methods=["GET"])
    async def signin_callback(request) -> HTMLResponse:
        status, page = await run_in_threadpool(callback_page, dict(request.query_params))
        return HTMLResponse(page, status_code=status, headers=_HEADERS)
