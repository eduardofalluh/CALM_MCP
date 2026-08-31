#!/usr/bin/env python3
"""Test script to validate CALM MCP OAuth endpoints.

Run this to verify the OAuth implementation is correct before deploying.
"""

import json

from src.calm.oauth import (
    build_www_authenticate_header,
    get_authorization_server_metadata,
    get_oauth_endpoints,
    get_protected_resource_metadata,
)


def test_oauth_endpoints():
    """Test OAuth endpoint generation."""
    print("=" * 80)
    print("Testing OAuth Endpoint Generation")
    print("=" * 80)

    endpoints = get_oauth_endpoints()
    print("\nOAuth Endpoints:")
    print(json.dumps(endpoints, indent=2))

    # Validate URLs
    assert endpoints["tenant"] == "illumiti-corp-cloudalm"
    assert endpoints["region"] == "eu10"
    assert "/oauth/authorize" in endpoints["authorization_endpoint"]
    assert "/oauth/token" in endpoints["token_endpoint"]
    assert "/oauth/token/oauth" not in endpoints["authorization_endpoint"], "Double path detected!"
    assert endpoints["issuer"].endswith("hana.ondemand.com")

    print("\n✅ OAuth endpoints are valid!")


def test_protected_resource_metadata():
    """Test RFC 9728 Protected Resource Metadata."""
    print("\n" + "=" * 80)
    print("Testing RFC 9728 Protected Resource Metadata")
    print("=" * 80)

    base_url = "https://illumiti-corp-cloudalm.eu10.alm.cloud.sap"
    metadata = get_protected_resource_metadata(base_url)
    print("\nProtected Resource Metadata:")
    print(json.dumps(metadata, indent=2))

    # Validate structure
    assert "resource" in metadata
    assert "authorization_servers" in metadata
    assert len(metadata["authorization_servers"]) > 0
    assert "scopes_supported" in metadata

    print("\n✅ Protected Resource Metadata is valid!")


def test_authorization_server_metadata():
    """Test RFC 8414 Authorization Server Metadata."""
    print("\n" + "=" * 80)
    print("Testing RFC 8414 Authorization Server Metadata")
    print("=" * 80)

    auth_url = "https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com"
    metadata = get_authorization_server_metadata(auth_url)
    print("\nAuthorization Server Metadata:")
    print(json.dumps(metadata, indent=2))

    # Validate structure
    assert "issuer" in metadata
    assert "authorization_endpoint" in metadata
    assert "token_endpoint" in metadata
    assert "grant_types_supported" in metadata
    assert "authorization_code" in metadata["grant_types_supported"]
    assert "refresh_token" in metadata["grant_types_supported"]
    assert "code_challenge_methods_supported" in metadata
    assert "S256" in metadata["code_challenge_methods_supported"]

    print("\n✅ Authorization Server Metadata is valid!")


def test_www_authenticate_header():
    """Test WWW-Authenticate header generation."""
    print("\n" + "=" * 80)
    print("Testing WWW-Authenticate Header")
    print("=" * 80)

    base_url = "https://illumiti-corp-cloudalm.eu10.alm.cloud.sap"

    # Test 401 response header
    header_401 = build_www_authenticate_header(
        base_url=base_url,
        scope="openid",
    )
    print("\n401 Unauthorized Header:")
    print(header_401)
    assert "Bearer" in header_401
    assert "resource_metadata=" in header_401
    assert "scope=" in header_401

    # Test 403 response header
    header_403 = build_www_authenticate_header(
        base_url=base_url,
        error="insufficient_scope",
        error_description="File write permission required",
        scope="files:write",
    )
    print("\n403 Forbidden Header:")
    print(header_403)
    assert "error=" in header_403
    assert "insufficient_scope" in header_403

    print("\n✅ WWW-Authenticate headers are valid!")


def main():
    """Run all tests."""
    print("\n🧪 CALM MCP OAuth Implementation Tests\n")

    try:
        test_oauth_endpoints()
        test_protected_resource_metadata()
        test_authorization_server_metadata()
        test_www_authenticate_header()

        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED!")
        print("=" * 80)
        print("\nThe OAuth implementation is ready for GenAI Studio integration.")
        print("\nNext steps:")
        print("1. Deploy the oauth-testing branch")
        print("2. Point GenAI Studio to the deployed MCP server")
        print("3. Call get_calm_oauth_endpoints tool to get OAuth URLs")
        print("4. Implement user login flow per OAUTH_IMPLEMENTATION_GUIDE.md")
        print("\n")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
