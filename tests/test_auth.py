"""Entra ID token validation with real RS256-signed JWTs (keys generated here)."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from conftest import make_settings
from fees import auth
from fees.config import load_settings
from fees.errors import ConfigurationError, ForbiddenError, UnauthorizedError

TENANT = "11111111-2222-3333-4444-555555555555"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SETTINGS = make_settings(mode="entra")


def token(key=KEY, **overrides):
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": "00000000-aaaa-bbbb-cccc-000000000000",
        "exp": int(time.time()) + 3600,
        "preferred_username": "Deep@Contoso.onmicrosoft.com",
        "roles": ["FeeAdmin"],
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256")


def authenticate(bearer):
    return auth.authenticate({"Authorization": f"Bearer {bearer}"}, SETTINGS, signing_key=KEY.public_key())


def test_valid_token_gives_user_and_roles():
    principal = authenticate(token())
    assert principal.user == "deep@contoso.onmicrosoft.com"
    assert principal.roles == {"FeeAdmin"}


def test_v1_token_issuer_and_uri_audience_are_accepted():
    principal = authenticate(token(iss=f"https://sts.windows.net/{TENANT}/", aud="api://fee-api"))
    assert principal.has_any("FeeAdmin")


@pytest.mark.parametrize("bad", [
    {"exp": int(time.time()) - 3600},                                   # expired
    {"aud": "api://some-other-api"},                                    # wrong audience
    {"iss": "https://login.microsoftonline.com/another-tenant/v2.0"},   # wrong tenant
    {"exp": None},                                                      # no expiry
])
def test_invalid_tokens_are_rejected(bad):
    with pytest.raises(UnauthorizedError):
        authenticate(token(**bad))


def test_token_signed_by_another_key_is_rejected():
    with pytest.raises(UnauthorizedError):
        authenticate(token(key=OTHER_KEY))


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "Bearer not-a-jwt"])
def test_missing_or_malformed_header(header):
    headers = {"Authorization": header} if header is not None else {}
    with pytest.raises(UnauthorizedError):
        auth.authenticate(headers, SETTINGS, signing_key=KEY.public_key())


def test_role_check():
    viewer = authenticate(token(roles=["FeeViewer"]))
    auth.require_any_role(viewer, "FeeAdmin", "FeeViewer")
    with pytest.raises(ForbiddenError):
        auth.require_any_role(viewer, "FeeAdmin")
    with pytest.raises(ForbiddenError):
        auth.require_any_role(authenticate(token(roles=None)), "FeeViewer")


def test_local_dev_mode_is_refused_in_azure(monkeypatch):
    monkeypatch.setenv("SqlConnectionString", "x")
    monkeypatch.setenv("AUTH_MODE", "local-dev")
    monkeypatch.setenv("WEBSITE_SITE_NAME", "fee-func")
    with pytest.raises(ConfigurationError):
        load_settings()


def test_entra_mode_needs_tenant_and_audience(monkeypatch):
    monkeypatch.setenv("SqlConnectionString", "x")
    monkeypatch.setenv("AUTH_MODE", "entra")
    monkeypatch.delenv("AUTH_TENANT_ID", raising=False)
    with pytest.raises(ConfigurationError):
        load_settings()
