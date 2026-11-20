"""Several SAP Cloud ALMs (customers) on one connection, picked per call with ``tenant``.

On the shared server a tenant is opened with its own key only for a person whose
SAP sign-in this server verified (signature, issuer, expiry) and who is on that
tenant's list; a local MCP is the user's own configuration. Keys are generated
here, hosts and people are made up.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.calm import tenants
from src.calm.dependencies import get_calm_headers, tenant_names

HOME_AUTH = "https://home-cloudalm.authentication.eu10.hana.ondemand.com"
ACME_AUTH = "https://acme-cloudalm.authentication.us10.hana.ondemand.com"
KEYS = {base: rsa.generate_private_key(public_exponent=65537, key_size=2048) for base in (HOME_AUTH, ACME_AUTH)}


def _jwk(private_key) -> dict:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return {**jwk, "kid": "key-1", "alg": "RS256", "use": "sig"}


def _token(email: str, auth: str = HOME_AUTH, key=None, **extra) -> str:
    claims = {"iss": f"{auth}/oauth/token", "exp": int(time.time()) + 600, "grant_type": "authorization_code",
              "user_name": email, "email": email, "given_name": "Jane", "family_name": "Doe", **extra}
    return jwt.encode(claims, key or KEYS[auth], algorithm="RS256", headers={"kid": "key-1"})


def _http(headers: dict):
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers=headers)))


LOCAL = SimpleNamespace(request_context=SimpleNamespace(request=None))


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    import os
    for var in [v for v in os.environ if v.startswith("CALM_TENANT_")] + [
            "CALM_BASE_URL", "CALM_AUTH_URL", "CALM_CLIENT_ID", "CALM_CLIENT_SECRET", "CALM_TOKEN",
            "CALM_MULTI_TENANT", "IDENTITY_ZONE", "REGION_ZONE"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CALM_IDENTITY_ZONE", "home-cloudalm")
    monkeypatch.setenv("CALM_REGION_ZONE", "eu10")
    for key, value in {"IDENTITY_ZONE": "acme-cloudalm", "REGION_ZONE": "us10", "CLIENT_ID": "acme-id",
                       "CLIENT_SECRET": "acme-secret",
                       "ALLOWED_USERS": "jane.doe@example.com, @partner.example"}.items():
        monkeypatch.setenv(f"CALM_TENANT_ACME_{key}", value)
    for key, value in {"IDENTITY_ZONE": "beta-cloudalm", "REGION_ZONE": "eu10", "CLIENT_ID": "beta-id",
                       "CLIENT_SECRET": "beta-secret"}.items():  # no list: nobody may use it
        monkeypatch.setenv(f"CALM_TENANT_BETA_{key}", value)
    monkeypatch.setattr(tenants, "_KEYS", {})
    fetched = []

    def fetch(base):
        fetched.append(base)
        return {"keys": [_jwk(KEYS[base])]}
    monkeypatch.setattr(tenants, "_fetch_jwks", fetch)
    opened = []

    def manager(client_id, client_secret, auth_url):
        opened.append((client_id, client_secret, auth_url))
        return SimpleNamespace(get_token=lambda: f"{client_id}-token")
    monkeypatch.setattr("src.calm.dependencies.get_or_create_token_manager", manager)
    return SimpleNamespace(fetched=fetched, opened=opened)


def test_local_mcp_opens_a_named_tenant_with_its_own_key(setup):
    for name in ("acme", "ACME", "acme-cloudalm"):
        h = get_calm_headers(LOCAL, name)
        assert h.base_url == "https://acme-cloudalm.us10.alm.cloud.sap" and h.token == "acme-id-token"
        assert h.token_source == "client_credentials (tenant acme)"
    assert setup.opened[0] == ("acme-id", "acme-secret", f"{ACME_AUTH}/oauth/token")
    assert tenant_names(LOCAL) == ["acme", "beta"]


def test_shared_server_needs_a_verified_sign_in(setup):
    with pytest.raises(ValueError, match="needs your own SAP sign-in"):
        get_calm_headers(_http({}), "acme")
    forged = _token("jane.doe@example.com", key=rsa.generate_private_key(public_exponent=65537, key_size=2048))
    expired = _token("jane.doe@example.com", exp=int(time.time()) - 3600)
    service = _token("jane.doe@example.com", grant_type="client_credentials")
    for token in (forged, expired, service, "not-a-jwt"):
        with pytest.raises(ValueError, match="needs your own SAP sign-in"):
            get_calm_headers(_http({"Authorization": f"Bearer {token}"}), "acme")
    stranger = _token("jane.doe@example.com", auth="https://evil.authentication.eu10.hana.ondemand.com",
                      key=KEYS[HOME_AUTH])
    with pytest.raises(ValueError, match="needs your own SAP sign-in"):
        get_calm_headers(_http({"Authorization": f"Bearer {stranger}"}), "acme")
    assert "https://evil.authentication.eu10.hana.ondemand.com" not in setup.fetched  # unknown login: never asked
    assert setup.opened == []


def test_person_on_the_list_gets_the_tenant_and_is_named(setup):
    h = get_calm_headers(_http({"Authorization": f"Bearer {_token('jane.doe@example.com')}"}), "acme")
    assert h.token == "acme-id-token" and h.base_url == "https://acme-cloudalm.us10.alm.cloud.sap"
    assert h.user_email == "jane.doe@example.com" and h.signed_in_user is None  # comments say "Added by"
    h = get_calm_headers(_http({"Authorization": f"Bearer {_token('Bob@Partner.example')}"}), "acme")
    assert h.token == "acme-id-token"  # @domain on the list
    assert setup.fetched == [HOME_AUTH]  # SAP's keys read once, then cached


def test_not_on_the_list_is_refused(setup):
    carol = _http({"Authorization": f"Bearer {_token('carol@example.com')}"})
    with pytest.raises(ValueError, match="not on the list.*CALM_TENANT_ACME_ALLOWED_USERS"):
        get_calm_headers(carol, "acme")
    lookalike = _http({"Authorization": f"Bearer {_token('dan@notpartner.example')}"})
    with pytest.raises(ValueError, match="not on the list"):
        get_calm_headers(lookalike, "acme")
    jane = _http({"Authorization": f"Bearer {_token('jane.doe@example.com')}"})
    with pytest.raises(ValueError, match="not on the list"):
        get_calm_headers(jane, "beta")  # a tenant with no list serves nobody
    with pytest.raises(ValueError, match='No SAP Cloud ALM called "gamma". Tenants you can use: acme\\.'):
        get_calm_headers(jane, "gamma")
    assert tenant_names(jane) == ["acme"] and tenant_names(carol) == [] and tenant_names(_http({})) == []
    assert setup.opened == []


def test_signed_in_to_that_very_tenant_uses_the_persons_token(setup):
    own = _token("jane.doe@example.com", auth=ACME_AUTH)
    h = get_calm_headers(_http({"Authorization": f"Bearer {own}"}), "acme")
    assert h.token == own and h.signed_in_user == "Jane Doe" and h.token_source == "signed-in user (OAuth), tenant acme"
    assert setup.opened == []


def test_a_single_tenant_connection_only_opens_its_own(setup):
    studio = _http({"x-calm-identity-zone": "acme-cloudalm", "x-calm-region-zone": "us10",
                    "x-calm-client-id": "studio-id", "x-calm-client-secret": "studio-secret"})
    h = get_calm_headers(studio, "acme")
    assert h.base_url == "https://acme-cloudalm.us10.alm.cloud.sap" and h.token == "studio-id-token"
    with pytest.raises(ValueError, match='set up for the SAP Cloud ALM "acme-cloudalm" only'):
        get_calm_headers(studio, "beta")


def test_an_incomplete_tenant_says_what_is_missing(monkeypatch):
    monkeypatch.setenv("CALM_TENANT_GAMMA_IDENTITY_ZONE", "gamma-cloudalm")
    with pytest.raises(ValueError, match="CALM_TENANT_GAMMA_REGION_ZONE, CALM_TENANT_GAMMA_CLIENT_ID, "
                                         "CALM_TENANT_GAMMA_CLIENT_SECRET not set"):
        get_calm_headers(LOCAL, "gamma")


def test_no_tenant_keeps_the_connection_default(setup, monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", "default-token")
    h = get_calm_headers(LOCAL)
    assert h.base_url == "https://home-cloudalm.eu10.alm.cloud.sap" and h.token == "default-token"
    assert get_calm_headers(LOCAL, "  ").token == "default-token"


def test_no_tenant_named_asks_which_one_instead_of_guessing(setup, monkeypatch):
    from src.calm.dependencies import TenantChoiceNeeded
    monkeypatch.setenv("CALM_TOKEN", "default-token")
    jane = _http({"Authorization": f"Bearer {_token('jane.doe@example.com')}"})
    with pytest.raises(TenantChoiceNeeded) as asked:
        get_calm_headers(jane, None, ask=True)
    assert asked.value.answer["status"] == "choose_tenant"
    assert asked.value.answer["Tenants"] == ["default (this connection's own SAP Cloud ALM)", "acme"]
    assert get_calm_headers(jane, "default", ask=True).base_url == "https://home-cloudalm.eu10.alm.cloud.sap"
    assert get_calm_headers(jane, None).base_url == "https://home-cloudalm.eu10.alm.cloud.sap"  # calm_health: no ask
    monkeypatch.setenv("CALM_DEFAULT_TENANT_NAME", "Syntax")
    assert get_calm_headers(jane, "syntax", ask=True).base_url == "https://home-cloudalm.eu10.alm.cloud.sap"
    with pytest.raises(TenantChoiceNeeded, match="Choices: syntax \\(this connection's own"):
        get_calm_headers(jane, "", ask=True)
    carol = _http({"Authorization": f"Bearer {_token('carol@example.com')}"})  # no client to choose from
    assert get_calm_headers(carol, None, ask=True).base_url == "https://home-cloudalm.eu10.alm.cloud.sap"
    assert setup.opened == []


def test_the_choice_lists_only_clients_when_there_is_no_default(setup, monkeypatch):
    from src.calm.dependencies import TenantChoiceNeeded
    monkeypatch.delenv("CALM_IDENTITY_ZONE")
    monkeypatch.delenv("CALM_REGION_ZONE")
    with pytest.raises(TenantChoiceNeeded) as asked:
        get_calm_headers(LOCAL, None, ask=True)
    assert asked.value.answer["Tenants"] == ["acme", "beta"]
