"""OAuth 2.0 Protected Resource Metadata (RFC 9728) for CALM MCP.

The MCP server declares itself as an OAuth-protected resource, advertising
CALM's authorization server endpoints so MCP clients (GenAI Studio) can
initiate user authentication flows.

See: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
"""

from __future__ import annotations

import os


def get_protected_resource_metadata(base_url: str | None = None) -> dict:
    """Return RFC 9728 Protected Resource Metadata for CALM.

    This tells MCP clients (GenAI Studio) where to send users for OAuth login.

    Args:
        base_url: CALM API base URL (e.g. https://my-tenant.eu10.alm.cloud.sap)
                  Extracted from env vars or request headers.

    Returns:
        Protected Resource Metadata document per RFC 9728
    """
    # Extract tenant and region from base_url or env vars
    from src.calm.config import get_base_url, parse_calm_url

    if not base_url:
        base_url = get_base_url()

    tenant, region = parse_calm_url(base_url)

    # Build authorization server URL
    # Auth URL format: https://<tenant>.authentication.<region>.hana.ondemand.com
    auth_server_issuer = f"https://{tenant}.authentication.{region}.hana.ondemand.com"

    # The resource identifier (canonical URI) - this is what clients pass as the
    # "resource" parameter during OAuth flow (RFC 8707)
    resource_uri = base_url.rstrip("/")

    return {
        # Required fields per RFC 9728
        "resource": resource_uri,
        "authorization_servers": [auth_server_issuer],

        # Optional: Scopes supported (minimal set for basic functionality)
        # MCP spec recommends listing minimal scopes here, with step-up auth
        # for additional permissions
        "scopes_supported": [
            "openid",  # Basic identity
        ],

        # Optional: Human-readable resource description
        "resource_documentation": "https://help.sap.com/docs/cloud-alm-api",

        # Optional: Indicate OAuth 2.1 support
        "oauth_2_0_version": "2.1",
    }


def get_authorization_server_metadata(auth_url: str, issuer: str | None = None) -> dict:
    """Return OAuth 2.0 Authorization Server Metadata (RFC 8414) for the tenant's SAP login.

    Only what SAP's login service (XSUAA) really does, read from its own
    /.well-known/openid-configuration: no client registration, so a client
    (Claude, GenAI Studio) signs in with the CALM API key's client ID + secret;
    no scope list, because asking for "openid" alone would leave the token
    without its CALM API permissions. ``issuer`` is this MCP server when it
    serves the document for its sign-in (Claude reads it from there).
    """
    base = auth_url.rstrip("/")
    return {
        "issuer": issuer or base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
    }


def public_mcp_url(headers: dict) -> str:
    """This server's MCP address as clients use it: MCP_PUBLIC_URL, else the request's host."""
    explicit = os.getenv("MCP_PUBLIC_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    host = (headers.get("x-forwarded-host") or headers.get("host") or "localhost").split(",")[0].strip()
    local = host.split(":")[0] in ("localhost", "127.0.0.1", "[::1]")
    proto = (headers.get("x-forwarded-proto") or ("http" if local else "https")).split(",")[0].strip()
    return f"{proto}://{host}/mcp"


def issuer_for(mcp_url: str) -> str:
    """The base the sign-in metadata lives under: the MCP address without its /mcp."""
    return mcp_url[: -len("/mcp")] if mcp_url.endswith("/mcp") else mcp_url


def connector_metadata(mcp_url: str) -> dict:
    """RFC 9728 metadata as Claude needs it: ``resource`` is exactly the MCP address
    and the authorization server is this server, which describes the SAP login."""
    return {
        "resource": mcp_url,
        "authorization_servers": [issuer_for(mcp_url)],
        "bearer_methods_supported": ["header"],
        "resource_documentation": "https://help.sap.com/docs/cloud-alm-api",
    }


def has_credential(headers: dict) -> bool:
    """Whether a request can reach CALM without signing in (same order as dependencies)."""
    if headers.get("authorization"):
        return True
    if headers.get("x-calm-client-id") and headers.get("x-calm-client-secret"):
        return True
    if os.getenv("CALM_MULTI_TENANT", "").strip().lower() in ("1", "true", "yes", "on"):
        return False  # a shared pod never falls back to its own credential
    return bool(os.getenv("CALM_TOKEN") or (os.getenv("CALM_CLIENT_ID") and os.getenv("CALM_CLIENT_SECRET")))


class OAuthMiddleware:
    """HTTP mode: serves the sign-in metadata, and answers an MCP request that has no
    credential at all with 401 + where to sign in (Claude only starts the SAP login
    on a 401). A request with any credential, or a server with its own, is untouched."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            response = self._answer(scope)
            if response is not None:
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    @staticmethod
    def _answer(scope):
        from starlette.responses import JSONResponse

        from src.calm.config import TenantNotConfiguredError, get_auth_base_url

        path = scope.get("path", "")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if path.startswith("/.well-known/oauth-protected-resource"):
            return JSONResponse(connector_metadata(public_mcp_url(headers)))
        if path.startswith(("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration")):
            try:
                auth_url = get_auth_base_url()
            except TenantNotConfiguredError as exc:
                return JSONResponse({"error": "tenant_not_configured", "error_description": str(exc)}, status_code=503)
            return JSONResponse(get_authorization_server_metadata(auth_url, issuer_for(public_mcp_url(headers))))
        if path.rstrip("/") == "/mcp" and scope.get("method") != "OPTIONS" and not has_credential(headers):
            where = f"{issuer_for(public_mcp_url(headers))}/.well-known/oauth-protected-resource"
            return JSONResponse(
                {"error": "invalid_token", "error_description": "Sign in to SAP Cloud ALM to use this connector."},
                status_code=401,
                headers={"WWW-Authenticate": f'Bearer resource_metadata="{where}"'},
            )
        return None


def build_www_authenticate_header(
    base_url: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    scope: str | None = None,
) -> str:
    """Build WWW-Authenticate header for 401/403 responses.

    Per RFC 6750 Section 3, this header tells clients:
    1. Where to find the Protected Resource Metadata (resource_metadata parameter)
    2. What scopes are required (scope parameter)
    3. What error occurred (error parameter)

    Args:
        base_url: CALM API base URL
        error: OAuth error code ("invalid_token", "insufficient_scope", etc.)
        error_description: Human-readable error description
        scope: Required scopes (space-separated string)

    Returns:
        WWW-Authenticate header value

    Example:
        WWW-Authenticate: Bearer resource_metadata="https://calm.example.com/.well-known/oauth-protected-resource",
                                 scope="openid",
                                 error="invalid_token"
    """
    from src.calm.config import get_base_url

    if not base_url:
        base_url = get_base_url()

    # Build the well-known metadata URL
    metadata_url = f"{base_url.rstrip('/')}/.well-known/oauth-protected-resource"

    # Start with Bearer scheme and metadata URL
    parts = [f'Bearer resource_metadata="{metadata_url}"']

    # Add optional parameters
    if scope:
        parts.append(f'scope="{scope}"')
    if error:
        parts.append(f'error="{error}"')
    if error_description:
        # Escape quotes in description
        escaped_desc = error_description.replace('"', '\\"')
        parts.append(f'error_description="{escaped_desc}"')

    return ", ".join(parts)


def get_oauth_endpoints() -> dict:
    """Return OAuth endpoints for the current CALM configuration.

    Helper function that combines auth server discovery with endpoint info.
    Used by GenAI Studio to configure OAuth flows.

    Returns:
        Dict with authorization_endpoint, token_endpoint, and tenant info
    """
    from src.calm.config import get_auth_base_url, get_base_url, parse_calm_url

    base_url = get_base_url()
    auth_base_url = get_auth_base_url()
    tenant, region = parse_calm_url(base_url)

    return {
        "tenant": tenant,
        "region": region,
        "authorization_endpoint": f"{auth_base_url}/oauth/authorize",
        "token_endpoint": f"{auth_base_url}/oauth/token",
        "revocation_endpoint": f"{auth_base_url}/oauth/revoke",
        "introspection_endpoint": f"{auth_base_url}/oauth/introspect",
        "jwks_uri": f"{auth_base_url}/oauth/token_keys",
        "issuer": auth_base_url,
        "resource": base_url.rstrip("/"),
        "metadata_url": f"{base_url.rstrip('/')}/.well-known/oauth-protected-resource",
        "scopes_supported": ["openid"],
    }
