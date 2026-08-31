"""OAuth endpoint discovery tool for MCP clients.

Exposes CALM's OAuth endpoints so GenAI Studio can configure user authentication.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import oauth
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:
    """Register OAuth discovery tool."""

    @mcp.tool()
    def get_calm_oauth_endpoints(ctx: Context) -> dict:
        """Get SAP Cloud ALM OAuth endpoints for user authentication.

        Returns the OAuth authorization server endpoints that GenAI Studio needs
        to implement user-delegated OAuth flows. This enables users to login with
        their own CALM credentials instead of using a shared service account.

        **Why OAuth?**
        - CALM History shows the actual user's name (not "API")
        - Each user's actions are tracked under their identity
        - Per-user permissions and access control

        **OAuth Flow:**
        1. GenAI Studio redirects user to authorization_endpoint
        2. User logs in with their SAP credentials
        3. CALM redirects back with authorization code
        4. GenAI Studio exchanges code for access_token at token_endpoint
        5. GenAI Studio sends user's access_token in Authorization header for each MCP request

        **Refresh Tokens:**
        SAP Cloud ALM OAuth DOES support refresh tokens. The token response includes:
        - access_token: Valid for 12 hours
        - refresh_token: Valid for ~30 days
        - expires_in: 43200 (12 hours)

        GenAI Studio should:
        1. Store the refresh_token securely per user
        2. Check if access_token is expired before each request
        3. Call token_endpoint with grant_type=refresh_token to get new access_token
        4. Update stored tokens
        5. If refresh fails (401), prompt user to re-authenticate

        Returns:
            Dict with all OAuth endpoints, tenant info, and implementation guidance
        """
        h = get_calm_headers(ctx)

        # Get the OAuth endpoints
        endpoints = oauth.get_oauth_endpoints()

        # Add implementation guidance
        endpoints["implementation_guide"] = {
            "step_1_redirect_user": {
                "url": endpoints["authorization_endpoint"],
                "parameters": {
                    "response_type": "code",
                    "client_id": "YOUR_OAUTH_CLIENT_ID",
                    "redirect_uri": "https://studio.ai.syntax-rnd.com/oauth/calm/callback",
                    "scope": "openid",
                    "state": "RANDOM_STATE_TOKEN",
                    "code_challenge": "BASE64URL(SHA256(random_string))",
                    "code_challenge_method": "S256",
                    "resource": endpoints["resource"],
                },
            },
            "step_2_exchange_code": {
                "url": endpoints["token_endpoint"],
                "method": "POST",
                "headers": {
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                "body": {
                    "grant_type": "authorization_code",
                    "code": "AUTHORIZATION_CODE_FROM_REDIRECT",
                    "redirect_uri": "https://studio.ai.syntax-rnd.com/oauth/calm/callback",
                    "client_id": "YOUR_OAUTH_CLIENT_ID",
                    "client_secret": "YOUR_OAUTH_CLIENT_SECRET",
                    "code_verifier": "RANDOM_STRING_FROM_STEP_1",
                    "resource": endpoints["resource"],
                },
                "response": {
                    "access_token": "eyJ...",
                    "refresh_token": "abc123...",
                    "expires_in": 43200,
                    "token_type": "Bearer",
                },
            },
            "step_3_refresh_token": {
                "url": endpoints["token_endpoint"],
                "method": "POST",
                "headers": {
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                "body": {
                    "grant_type": "refresh_token",
                    "refresh_token": "USER_REFRESH_TOKEN",
                    "client_id": "YOUR_OAUTH_CLIENT_ID",
                    "client_secret": "YOUR_OAUTH_CLIENT_SECRET",
                    "resource": endpoints["resource"],
                },
            },
            "step_4_use_token": {
                "description": "Send user's access_token in every MCP request",
                "header": "Authorization: Bearer USER_ACCESS_TOKEN",
                "note": "MCP server will validate the token and extract user identity",
            },
        }

        endpoints["refresh_token_support"] = {
            "supported": True,
            "access_token_lifetime": "12 hours (43200 seconds)",
            "refresh_token_lifetime": "~30 days (varies by tenant config)",
            "rotation": "New refresh_token issued on each token refresh",
            "recommendation": "Store refresh_token securely, refresh access_token in background before expiry",
        }

        endpoints["user_experience"] = {
            "with_refresh_token": "Login once, works for ~30 days (until refresh token expires)",
            "without_refresh_token": "Re-login every 12 hours when access token expires",
        }

        return endpoints

    @mcp.tool()
    def get_calm_oauth_metadata(ctx: Context) -> dict:
        """Get OAuth 2.0 Protected Resource Metadata (RFC 9728).

        Returns the metadata document that MCP clients use to discover the
        authorization server and required scopes. This is the entry point for
        MCP OAuth flows per the MCP specification.

        The metadata is also available at:
        GET {base_url}/.well-known/oauth-protected-resource

        Returns:
            RFC 9728 Protected Resource Metadata document
        """
        h = get_calm_headers(ctx)
        return oauth.get_protected_resource_metadata(h.base_url)

    @mcp.tool()
    def get_calm_authorization_server_metadata(ctx: Context) -> dict:
        """Get OAuth 2.0 Authorization Server Metadata (RFC 8414).

        Returns the authorization server's capabilities and endpoints.
        MCP clients fetch this after discovering the authorization server
        from the Protected Resource Metadata.

        The metadata is also available at:
        GET {auth_url}/.well-known/oauth-authorization-server

        Returns:
            RFC 8414 Authorization Server Metadata document
        """
        h = get_calm_headers(ctx)
        from src.calm.config import get_auth_url

        auth_url = get_auth_url()
        return oauth.get_authorization_server_metadata(auth_url)
