"""
CALM credential resolution.

Resolution order:
  0. A person's own SAP sign-in token in Authorization: Bearer (OAuth, e.g. from
     GenAI Studio) — first, so CALM records that person, not the service key's "API".
  1. Client credentials from request headers — x-calm-client-id + x-calm-client-secret
     (preferred for HTTP/multi-tenant; GenAI Studio injects these per customer).
  2. Server-startup token manager — CALM_CLIENT_ID + CALM_CLIENT_SECRET env vars.
  3. Authorization: Bearer <token> request header — HTTP legacy / per-request.
  4. CALM_TOKEN env var — stdio / local dev, static token.

Auth URL resolution order:
  x-calm-auth-url header (full URL) > zone headers (x-calm-identity-zone + x-calm-region-zone) > env vars.

Base URL resolution order:
  x-calm-base-url header > zone headers > env vars.
  There is no built-in tenant: if none of these supply one, TenantNotConfiguredError.

Several tenants on one connection (``tenant`` on the tools, see tenants.py):
  a named tenant is opened with its own server-configured key; on the HTTP server
  only for a person whose SAP sign-in this server verified and who is on that
  tenant's list (their own token when they signed in to that very tenant).

Cross-tenant safety (fail-closed):
  The server env credential (CALM_CLIENT_ID/SECRET) belongs to ONE tenant. In a
  shared multi-tenant pod (e.g. GenAI Studio), falling back to it for a request
  that was meant for a different tenant would silently return the WRONG tenant's
  data. To prevent that:
    - If a request carries any per-tenant routing signal (x-calm-client-id,
      x-calm-identity-zone/region-zone, x-calm-auth-url, or x-calm-base-url) but
      NOT a complete x-calm-client-id + x-calm-client-secret pair, the server
      raises instead of falling back to the env credential.
    - If CALM_MULTI_TENANT is truthy, EVERY request must carry the header
      credential pair; the env-credential fallback is disabled entirely.
  When no routing signal is present and CALM_MULTI_TENANT is unset, behavior is
  unchanged (env/bearer/CALM_TOKEN fallback for single-tenant and local dev).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os

from fastmcp import Context

from . import tenants
from .config import TenantNotConfiguredError, build_auth_url, build_base_url, get_auth_url, get_base_url
from .models import CALMHeaders
from .token_manager import get_managed_token, get_or_create_token_manager

log = logging.getLogger("calm-mcp.auth")


def _fp(secret: str | None) -> str:
    """Non-reversible fingerprint of a secret for logs: '<len>:<sha256[:8]>'.

    Never returns the secret itself — just enough to tell two secrets apart and
    spot truncation. 'none' when absent.
    """
    if not secret:
        return "none"
    return f"{len(secret)}:{hashlib.sha256(secret.encode()).hexdigest()[:8]}"


def _multi_tenant_mode() -> bool:
    """When truthy, the shared pod must never fall back to its env credential."""
    return os.getenv("CALM_MULTI_TENANT", "").strip().lower() in ("1", "true", "yes", "on")


def writes_enabled() -> bool:
    """Whether write tools are permitted. Off unless CALM_ENABLE_WRITES is truthy."""
    return os.getenv("CALM_ENABLE_WRITES", "").strip().lower() in ("1", "true", "yes", "on")


def ensure_writes_enabled() -> None:
    """Raise a clear error if write operations are disabled."""
    if not writes_enabled():
        raise ValueError(
            "Write operations are disabled. Set CALM_ENABLE_WRITES=true to enable "
            "create/update tools. This guard prevents accidental changes to the tenant."
        )


def _token_from_authorization(value: str | None) -> str | None:
    if not value:
        return None

    raw_token = value.strip()
    scheme, _, token = raw_token.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return raw_token


def signed_in_person(token: str | None) -> str | None:
    """The person a SAP sign-in token was issued to (OAuth, e.g. from GenAI Studio),
    or None for a service key's token or anything that isn't a SAP user token.
    Only reads the token's claims; SAP itself checks the token on every call."""
    try:
        part = str(token or "").split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:  # noqa: BLE001 — not a JWT: not a person's sign-in
        return None
    if (not isinstance(claims, dict) or claims.get("grant_type") in (None, "", "client_credentials")
            or not claims.get("user_name")):
        return None
    name = " ".join(str(claims.get(k) or "").strip() for k in ("given_name", "family_name")).strip()
    return name or claims.get("email") or str(claims["user_name"])


def _request(ctx: Context):
    try:
        return ctx.request_context.request
    except Exception:  # noqa: BLE001 — no request: a local (stdio) MCP
        return None


def tenant_names(ctx: Context) -> list[str]:
    """The tenants this caller may pick with ``tenant`` (every one on a local MCP)."""
    everyone = tenants.configured()
    request = _request(ctx)
    if request is None:
        return sorted(everyone)
    person = tenants.verified_person(_token_from_authorization(request.headers.get("Authorization")))
    return sorted(n for n, t in everyone.items() if person and tenants.allows(t, person))


def _tenant_headers(ctx: Context, name: str) -> CALMHeaders:
    """Credentials for the tenant the caller named (see tenants.py)."""
    request = _request(ctx)
    hdrs = request.headers if request is not None else {}
    bearer = _token_from_authorization(hdrs.get("Authorization"))
    everyone = list(tenants.configured().values())
    person = None
    if request is None:  # a local MCP: the user's own machine and configuration
        choices = everyone
    else:
        person = tenants.verified_person(bearer)
        if person is None:
            zone_hdr = (hdrs.get("x-calm-identity-zone") or "").strip()
            if zone_hdr:  # a connection set up for one tenant (GenAI Studio headers): that one only
                named = tenants.find(name, everyone)
                if tenants.norm(zone_hdr) in (tenants.norm(name), tenants.norm(named.identity_zone if named else "")):
                    return get_calm_headers(ctx)
                raise ValueError(
                    f'This connection is set up for the SAP Cloud ALM "{zone_hdr}" only, so it can\'t open '
                    f'tenant "{name}". Leave tenant empty, or use the connection for that tenant.')
            raise ValueError(
                f'Choosing a SAP Cloud ALM (tenant "{name}") needs your own SAP sign-in on this connection, '
                "so the server knows who is asking. Connect / sign in to the SAP Cloud ALM connector, "
                "or leave tenant empty to use the connection's default.")
        choices = [t for t in everyone if tenants.allows(t, person)]
    entry = tenants.find(name, choices)
    if entry is None:
        exists = person is not None and tenants.find(name, everyone)
        if exists:
            raise ValueError(
                f'You are not on the list of people who may use the SAP Cloud ALM "{exists.name}". '
                f"Ask the MCP's administrator to add you (CALM_TENANT_{exists.name.upper()}_ALLOWED_USERS).")
        raise ValueError(
            f'No SAP Cloud ALM called "{name}". Tenants you can use: '
            f'{", ".join(t.name for t in choices) or "none"}. Leave tenant empty for the connection\'s default.')
    if entry.missing:
        raise ValueError(f'The SAP Cloud ALM "{entry.name}" is not fully set up on the server: '
                         f'{", ".join(entry.missing)} not set.')
    if person is not None and person.get("iss") == entry.auth_url:
        # They signed in to this very tenant: their own token, so CALM records them.
        token, source = bearer, f"signed-in user (OAuth), tenant {entry.name}"
    else:
        token = get_or_create_token_manager(entry.client_id, entry.client_secret, entry.auth_url).get_token()
        source = f"client_credentials (tenant {entry.name})"
    log.info("CALM auth path=TENANT %s caller=%s source=%s base_url=%s",
             entry.name, "verified person" if person else "local", source, entry.base_url)
    email = (tenants.person_email(person) if person else None) or hdrs.get("x-user-email") \
        or os.getenv("CALM_USER_EMAIL")
    return CALMHeaders(token=token, base_url=entry.base_url, token_source=source, user_email=email,
                       signed_in_user=signed_in_person(token))


def get_calm_headers(ctx: Context, tenant: str | None = None) -> CALMHeaders:
    if tenant is not None and str(tenant).strip():
        return _tenant_headers(ctx, str(tenant).strip())
    token: str | None = None
    base_url: str | None = None
    token_source: str | None = None
    user_email: str | None = None

    identity_zone: str | None = None
    region_zone: str | None = None
    client_id_hdr: str | None = None
    client_secret_hdr: str | None = None
    auth_bearer_token: str | None = None
    auth_url_hdr: str | None = None

    # Read all CALM-related request headers in one pass
    try:
        request = ctx.request_context.request
        if request is not None:
            h = request.headers
            identity_zone = h.get("x-calm-identity-zone") or None
            region_zone = h.get("x-calm-region-zone") or None
            client_id_hdr = h.get("x-calm-client-id")
            client_secret_hdr = h.get("x-calm-client-secret")
            # Trim stray whitespace/newlines some header pipelines add. A trailing
            # \r\n or space on the secret corrupts the Base64 Basic-auth and causes
            # a misleading XSUAA 401 "Bad credentials". Record if we had to, so a
            # mangled-forward shows up in the logs.
            if client_id_hdr and client_id_hdr != client_id_hdr.strip():
                log.warning("x-calm-client-id had surrounding whitespace — trimming")
                client_id_hdr = client_id_hdr.strip()
            if client_secret_hdr and client_secret_hdr != client_secret_hdr.strip():
                log.warning(
                    "x-calm-client-secret had surrounding whitespace — trimming (len %d -> %d)",
                    len(client_secret_hdr), len(client_secret_hdr.strip()),
                )
                client_secret_hdr = client_secret_hdr.strip()
            auth_bearer_token = _token_from_authorization(h.get("Authorization"))
            raw_auth = h.get("x-calm-auth-url")
            if raw_auth and raw_auth.strip().startswith("https://"):
                auth_url_hdr = raw_auth.strip()
            raw_base = h.get("x-calm-base-url")
            if raw_base and raw_base.strip().startswith("https://"):
                base_url = raw_base.strip()
            # User email from GenAI Studio (x-user-email) or other headers
            user_email = (h.get("x-user-email") or
                         h.get("x-forwarded-user") or
                         h.get("x-calm-user-email") or None)
    except Exception:
        pass

    # A per-tenant routing signal means the caller intends a SPECIFIC tenant.
    base_url_hdr = base_url  # set above ONLY if x-calm-base-url was provided
    has_header_creds = bool(client_id_hdr and client_secret_hdr)
    tenant_signal = bool(
        client_id_hdr or client_secret_hdr or identity_zone
        or region_zone or auth_url_hdr or base_url_hdr
    )

    # Diagnostic: what the request actually carried (fingerprint only, never the secret).
    log.info(
        "CALM headers in: client_id=%s client_secret_fp=%s identity_zone=%s region_zone=%s "
        "auth_url_hdr=%s base_url_hdr=%s bearer=%s tenant_signal=%s multi_tenant=%s",
        client_id_hdr or "-", _fp(client_secret_hdr), identity_zone or "-", region_zone or "-",
        auth_url_hdr or "-", base_url_hdr or "-", "yes" if auth_bearer_token else "no",
        tenant_signal, _multi_tenant_mode(),
    )

    # Resolve base URL: explicit header > zone headers > env vars.
    # A missing tenant is raised only after the credential checks below, so the
    # fail-closed credential errors keep their priority.
    tenant_error: TenantNotConfiguredError | None = None
    if not base_url:
        try:
            if identity_zone or region_zone:
                base_url = build_base_url(identity_zone, region_zone)
            else:
                base_url = get_base_url()
        except TenantNotConfiguredError as exc:
            tenant_error = exc

    # --- 0. The signed-in person's own SAP token (OAuth) ---
    # SAP then records that person (history, comment author, creator) instead of
    # the service key's technical user ("API"), so it goes before any service key.
    # Any other Authorization header keeps its place (step 3).
    if signed_in_person(auth_bearer_token):
        log.info("CALM auth path=SIGNED-IN USER (OAuth) base_url=%s", base_url)
        token = auth_bearer_token
        token_source = "signed-in user (OAuth)"

    # --- 1. Client credentials from request headers (per-tenant OAuth) ---
    if not token and has_header_creds:
        if auth_url_hdr:
            auth_url = auth_url_hdr
        elif identity_zone or region_zone:
            auth_url = build_auth_url(identity_zone, region_zone)
        else:
            auth_url = get_auth_url()
        log.info(
            "CALM auth path=HEADER (per-tenant) client_id=%s secret_fp=%s auth_url=%s base_url=%s",
            client_id_hdr, _fp(client_secret_hdr), auth_url, base_url,
        )
        mgr = get_or_create_token_manager(client_id_hdr, client_secret_hdr, auth_url)
        token = mgr.get_token()
        token_source = "client_credentials (header)"

    # --- 2. Server env credential (shared, single-tenant) ---
    # ONLY when the request carries NO per-tenant routing signal and multi-tenant
    # mode is off. Using it for a request meant for another tenant would silently
    # return the WRONG tenant's data — the "wrong projects" bug — so it is skipped
    # whenever a routing signal is present or CALM_MULTI_TENANT is set.
    env_fallback_allowed = (not tenant_signal) and (not _multi_tenant_mode())
    if not token and env_fallback_allowed:
        log.info(
            "CALM auth path=ENV (shared server credential) env_client_id=%s env_secret_fp=%s base_url=%s",
            os.getenv("CALM_CLIENT_ID") or "-", _fp(os.getenv("CALM_CLIENT_SECRET")), base_url,
        )
        managed = get_managed_token()
        if managed:
            token = managed
            token_source = "client_credentials"

    # --- 3. Authorization: Bearer header (HTTP legacy / self-contained per-request) ---
    if not token and auth_bearer_token:
        token = auth_bearer_token
        token_source = "Authorization header"

    # --- 4. CALM_TOKEN env var (stdio / local dev) ---
    # Same guard as the env credential: a request carrying its own tenant
    # routing (e.g. x-calm-base-url) must never receive the server's token,
    # or a caller could send it to a host of their choosing.
    if not token and env_fallback_allowed:
        env_token = os.getenv("CALM_TOKEN")
        if env_token:
            token = env_token.strip()
            token_source = "CALM_TOKEN env var"

    if not token:
        # Fail-closed: give a tenant-aware error instead of silently serving the
        # shared env credential (which belongs to a different tenant).
        if tenant_signal and not has_header_creds:
            log.warning(
                "CALM auth path=REFUSED (incomplete per-tenant credentials) client_id=%s "
                "secret_fp=%s identity_zone=%s base_url=%s — not falling back to env credential",
                client_id_hdr or "-", _fp(client_secret_hdr), identity_zone or "-", base_url,
            )
            raise ValueError(
                "Incomplete per-tenant credentials: this request carries tenant routing "
                "(x-calm-client-id / x-calm-identity-zone / x-calm-base-url) but not a complete "
                "x-calm-client-id + x-calm-client-secret pair. Refusing to fall back to the shared "
                "server credential, which would return a DIFFERENT tenant's data. Verify the "
                "connection forwards BOTH x-calm-client-id and x-calm-client-secret on every request."
            )
        if _multi_tenant_mode():
            log.warning(
                "CALM auth path=REFUSED (CALM_MULTI_TENANT set, no header credentials) base_url=%s",
                base_url,
            )
            raise ValueError(
                "CALM_MULTI_TENANT is enabled: every request must provide x-calm-client-id + "
                "x-calm-client-secret headers. The server env credential belongs to a single tenant "
                "and will not be used, to avoid serving the wrong tenant's data."
            )
        if tenant_error and os.getenv("CALM_CLIENT_ID"):
            # Env credentials exist but can't be used without a tenant; name
            # that cause instead of a generic "missing token".
            raise tenant_error
        raise ValueError(
            "Missing CALM token. Options:\n"
            "  HTTP headers: x-calm-client-id + x-calm-client-secret (+ optional x-calm-identity-zone, x-calm-region-zone)\n"
            "  Server env vars: CALM_CLIENT_ID + CALM_CLIENT_SECRET\n"
            "  Per-request: Authorization: Bearer <token>\n"
            "  Local dev: CALM_TOKEN env var"
        )

    if tenant_error:
        raise tenant_error

    # Fallback to env var if no header provided
    if not user_email:
        user_email = os.getenv("CALM_USER_EMAIL")

    return CALMHeaders(token=token, base_url=base_url, token_source=token_source, user_email=user_email,
                       signed_in_user=signed_in_person(token))
