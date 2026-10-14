"""Azure AD (Microsoft Entra ID) authentication and role-based access.

Admin endpoints require a Bearer access token issued by Entra ID for this
API. The token is validated here (signature, expiry, issuer, audience) and
its 'roles' claim decides what the caller may do:

    FeeAdmin   read and update fee records
    FeeViewer  read only

API Management validates the same token at the gateway; checking again in
the Function is defence in depth (the Function is still protected if someone
reaches it directly with a function key).

AUTH_MODE=local-dev (refused when running in Azure) reads the identity from
X-Dev-User / X-Dev-Roles headers so the API can be exercised on a laptop
without Entra ID.
"""

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from .config import AUTH_MODE_LOCAL_DEV, Settings
from .errors import ForbiddenError, UnauthorizedError

ROLE_ADMIN = "FeeAdmin"
ROLE_VIEWER = "FeeViewer"

_jwk_clients: dict[str, PyJWKClient] = {}


@dataclass(frozen=True)
class Principal:
    user: str
    roles: frozenset[str]

    def has_any(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


def _jwk_client(tenant_id: str) -> PyJWKClient:
    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    if url not in _jwk_clients:
        _jwk_clients[url] = PyJWKClient(url, cache_keys=True, lifespan=3600)
    return _jwk_clients[url]


def _allowed_issuers(tenant_id: str) -> set[str]:
    # v2.0 tokens and v1.0 tokens use different issuer formats.
    return {
        f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        f"https://sts.windows.net/{tenant_id}/",
    }


def decode_token(token: str, settings: Settings, signing_key=None) -> dict:
    try:
        key = signing_key or _jwk_client(settings.tenant_id).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=list(settings.audiences),
            options={"require": ["exp", "iss", "aud"]},
            leeway=60,
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("The access token has expired.") from exc
    except (jwt.PyJWTError, ValueError) as exc:
        raise UnauthorizedError("The access token is invalid.") from exc

    if claims.get("iss") not in _allowed_issuers(settings.tenant_id):
        raise UnauthorizedError("The access token was issued by an untrusted tenant.")
    return claims


def authenticate(headers, settings: Settings, signing_key=None) -> Principal:
    if settings.auth_mode == AUTH_MODE_LOCAL_DEV:
        user = (headers.get("X-Dev-User") or "").strip()
        if not user:
            raise UnauthorizedError("Local dev mode: send an X-Dev-User header.")
        roles = {r.strip() for r in (headers.get("X-Dev-Roles") or "").split(",") if r.strip()}
        return Principal(user=user.lower(), roles=frozenset(roles))

    auth_header = headers.get("Authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError("Send an Entra ID access token as 'Authorization: Bearer <token>'.")

    claims = decode_token(token.strip(), settings, signing_key)
    user = claims.get("preferred_username") or claims.get("upn") or claims.get("email") or claims.get("oid", "")
    return Principal(user=str(user).lower(), roles=frozenset(claims.get("roles", [])))


def require_any_role(principal: Principal, *roles: str) -> None:
    if not principal.has_any(*roles):
        raise ForbiddenError(
            "Your account does not have the required role for this operation.",
            {"requiredAnyOf": list(roles), "yourRoles": sorted(principal.roles)},
        )
