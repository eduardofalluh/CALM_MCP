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
        base_url: CALM API base URL (e.g. https://illumiti-corp-cloudalm.eu10.alm.cloud.sap)
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


def get_authorization_server_metadata(auth_url: str) -> dict:
    """Return OAuth 2.0 Authorization Server Metadata (RFC 8414).

    This describes the CALM OAuth server's capabilities and endpoints.
    MCP clients fetch this after discovering the authorization server from
    the Protected Resource Metadata.

    Args:
        auth_url: CALM auth server base URL
                  (e.g. https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com)

    Returns:
        Authorization Server Metadata per RFC 8414
    """
    base = auth_url.rstrip("/")

    return {
        # Required fields per RFC 8414
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",

        # Supported grant types
        "grant_types_supported": [
            "authorization_code",
            "refresh_token",
            "client_credentials",  # For service accounts
        ],

        # Response types supported
        "response_types_supported": ["code"],

        # PKCE support (required by MCP spec)
        "code_challenge_methods_supported": ["S256"],

        # Token endpoint auth methods
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "none",  # For public clients using PKCE
        ],

        # Scopes (minimal set - additional scopes requested via step-up)
        "scopes_supported": [
            "openid",
        ],

        # Optional: Refresh token support
        # SAP Cloud ALM DOES support refresh tokens
        "refresh_token_rotation_supported": True,

        # Optional: RFC 9207 - Authorization Response Issuer Identification
        # Indicates that authorization responses include the "iss" parameter
        "authorization_response_iss_parameter_supported": True,

        # Optional: RFC 8707 - Resource Indicators support
        "resource_parameter_supported": True,

        # Optional: Metadata endpoints
        "revocation_endpoint": f"{base}/oauth/revoke",
        "introspection_endpoint": f"{base}/oauth/introspect",

        # Optional: Discovery endpoint
        "jwks_uri": f"{base}/oauth/token_keys",

        # Optional: UI locales supported
        "ui_locales_supported": ["en", "de", "fr", "es", "pt", "ja", "zh"],
    }


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
