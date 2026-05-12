"""Cloud ALM tenant URL configuration."""

from __future__ import annotations

import os

DEFAULT_IDENTITY_ZONE = "illumiti-corp-cloudalm"
DEFAULT_REGION_ZONE = "eu10"


def get_identity_zone() -> str:
    return (
        os.getenv("CALM_IDENTITY_ZONE")
        or os.getenv("IDENTITY_ZONE")
        or DEFAULT_IDENTITY_ZONE
    )


def get_region_zone() -> str:
    return (
        os.getenv("CALM_REGION_ZONE")
        or os.getenv("REGION_ZONE")
        or DEFAULT_REGION_ZONE
    )


def build_auth_url(identity_zone: str | None = None, region_zone: str | None = None) -> str:
    identity = identity_zone or get_identity_zone()
    region = region_zone or get_region_zone()
    return f"https://{identity}.authentication.{region}.hana.ondemand.com/oauth/token"


def build_base_url(identity_zone: str | None = None, region_zone: str | None = None) -> str:
    identity = identity_zone or get_identity_zone()
    region = region_zone or get_region_zone()
    return f"https://{identity}.{region}.alm.cloud.sap"


def get_auth_url() -> str:
    return os.getenv("CALM_AUTH_URL") or build_auth_url()


def get_base_url() -> str:
    return os.getenv("CALM_BASE_URL") or build_base_url()
