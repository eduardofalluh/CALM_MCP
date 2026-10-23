"""Cloud ALM tenant URL configuration."""

from __future__ import annotations

import os


class TenantNotConfiguredError(ValueError):
    """No CALM tenant was supplied by env vars or request headers.

    There is deliberately no built-in tenant: an unconfigured server must fail
    instead of silently answering for whichever tenant happened to be the default.
    """


_TENANT_NOT_CONFIGURED = (
    "No SAP Cloud ALM tenant configured. Set IDENTITY_ZONE and REGION_ZONE "
    "(or CALM_IDENTITY_ZONE / CALM_REGION_ZONE) on the server, or explicit "
    "CALM_BASE_URL and CALM_AUTH_URL; or send x-calm-identity-zone + "
    "x-calm-region-zone (or x-calm-base-url / x-calm-auth-url) headers per request."
)


def get_identity_zone() -> str:
    zone = os.getenv("CALM_IDENTITY_ZONE") or os.getenv("IDENTITY_ZONE")
    if not zone:
        raise TenantNotConfiguredError(_TENANT_NOT_CONFIGURED)
    return zone


def get_region_zone() -> str:
    zone = os.getenv("CALM_REGION_ZONE") or os.getenv("REGION_ZONE")
    if not zone:
        raise TenantNotConfiguredError(_TENANT_NOT_CONFIGURED)
    return zone


def build_auth_url(identity_zone: str | None = None, region_zone: str | None = None) -> str:
    identity = identity_zone or get_identity_zone()
    region = region_zone or get_region_zone()
    return f"https://{identity}.authentication.{region}.hana.ondemand.com/oauth/token"


def build_auth_base_url(identity_zone: str | None = None, region_zone: str | None = None) -> str:
    """Build OAuth authorization server base URL (without /oauth/token path).

    Used for OAuth endpoint discovery - returns just the base issuer URL.
    build_auth_url() includes /oauth/token for backwards compatibility with token requests.
    """
    identity = identity_zone or get_identity_zone()
    region = region_zone or get_region_zone()
    return f"https://{identity}.authentication.{region}.hana.ondemand.com"


def build_cert_auth_url(identity_zone: str | None = None, region_zone: str | None = None) -> str:
    """mTLS (x509) token host — note the '.cert.' segment. Used for certificate-based
    service keys, which authenticate with a client certificate instead of a secret."""
    identity = identity_zone or get_identity_zone()
    region = region_zone or get_region_zone()
    return f"https://{identity}.authentication.cert.{region}.hana.ondemand.com/oauth/token"


def get_cert_auth_url() -> str:
    return os.getenv("CALM_CERT_AUTH_URL") or build_cert_auth_url()


def build_base_url(identity_zone: str | None = None, region_zone: str | None = None) -> str:
    identity = identity_zone or get_identity_zone()
    region = region_zone or get_region_zone()
    return f"https://{identity}.{region}.alm.cloud.sap"


def get_auth_url() -> str:
    return os.getenv("CALM_AUTH_URL") or build_auth_url()


def get_auth_base_url() -> str:
    """Get OAuth authorization server base URL (without /oauth/token path).

    Falls back to extracting base from CALM_AUTH_URL if it contains /oauth/token.
    """
    url = os.getenv("CALM_AUTH_URL")
    if url:
        # Strip /oauth/token if present
        return url.replace("/oauth/token", "")
    return build_auth_base_url()


def get_base_url() -> str:
    return os.getenv("CALM_BASE_URL") or build_base_url()


def parse_calm_url(url: str) -> tuple[str, str]:
    """Extract tenant and region from a CALM URL.

    Args:
        url: CALM URL (e.g. https://my-tenant.eu10.alm.cloud.sap
             or https://my-tenant.authentication.eu10.hana.ondemand.com)

    Returns:
        Tuple of (tenant, region)

    Example:
        >>> parse_calm_url("https://my-tenant.eu10.alm.cloud.sap")
        ('my-tenant', 'eu10')
    """
    # Remove protocol
    url = url.replace("https://", "").replace("http://", "")

    # Handle both API and auth URLs
    # API: tenant.region.alm.cloud.sap
    # Auth: tenant.authentication.region.hana.ondemand.com
    parts = url.split(".")

    if "authentication" in parts:
        # Auth URL format: tenant.authentication.region.hana.ondemand.com
        tenant = parts[0]
        region = parts[2]  # Skip 'authentication'
    else:
        # API URL format: tenant.region.alm.cloud.sap
        tenant = parts[0]
        region = parts[1]

    return tenant, region
