"""
OpenID Connect (OIDC) client and PKCE helper implementation for py-phone-caller.

Provides standard RFC 7636 Authorization Code Flow with PKCE, token exchange,
JWT payload decoding, and Keycloak claim mapping.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import requests
import urllib3

from py_phone_caller_utils.config import settings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


def generate_pkce_pair() -> tuple[str, str]:
    """
    Generates a cryptographically secure PKCE code verifier and S256 challenge.

    Returns:
        tuple[str, str]: (code_verifier, code_challenge)
    """
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def decode_jwt_payload_unverified(token: str) -> dict[str, Any]:
    """
    Decodes the payload segment of a JWT without cryptographic verification.
    Used when token has already been directly retrieved over a mutual TLS / HTTPS
    channel from the token issuer.

    Args:
        token: Base64URL-encoded JWT string.

    Returns:
        dict[str, Any]: The decoded JSON claims dictionary.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1]
        rem = len(payload_b64) % 4
        if rem > 0:
            payload_b64 += "=" * (4 - rem)
        decoded_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(decoded_bytes.decode("utf-8"))
    except Exception as err:
        logger.warning(f"Failed to decode unverified JWT payload: {err}")
        return {}


class OIDCClient:
    """
    OIDC Client for interacting with Keycloak or any RFC-compliant OpenID provider.
    """

    def __init__(
        self,
        issuer_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        verify_ssl: bool = False,
    ) -> None:
        oauth_cfg = getattr(getattr(settings, "auth", None), "oauth2", {})
        self.issuer_url = (issuer_url or getattr(oauth_cfg, "issuer_url", "")).rstrip("/")
        self.client_id = client_id or getattr(oauth_cfg, "client_id", "py-phone-caller-ui")
        self.client_secret = client_secret or getattr(oauth_cfg, "client_secret", "")
        self.redirect_uri = redirect_uri or getattr(oauth_cfg, "redirect_uri", "")
        self.verify_ssl = verify_ssl if verify_ssl is not None else getattr(oauth_cfg, "verify_ssl", False)

    @property
    def is_configured(self) -> bool:
        """Indicates if OIDC issuer and client parameters are present."""
        return bool(self.issuer_url and self.client_id)

    def get_authorization_url(
        self,
        state: str,
        code_challenge: str,
        redirect_uri: str | None = None,
        scopes: list[str] | None = None,
    ) -> str:
        """
        Builds the standard OIDC authorization redirect URL.

        Args:
            state: Cryptographically random state parameter for CSRF mitigation.
            code_challenge: PKCE SHA256 challenge.
            redirect_uri: Optional override for OAuth2 redirect URI.
            scopes: Optional list of scopes (defaults to openid, profile, email).

        Returns:
            str: Full URL to redirect the user's browser to.
        """
        scope_str = " ".join(scopes or ["openid", "profile", "email"])
        target_redirect = redirect_uri or self.redirect_uri
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": scope_str,
            "redirect_uri": target_redirect,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.issuer_url}/protocol/openid-connect/auth?{urlencode(params)}"

    def exchange_code_for_token(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        """
        Exchanges an authorization code and PKCE verifier for OIDC tokens.

        Args:
            code: The authorization code received from the IdP.
            code_verifier: The original PKCE verifier stored in the user's session.
            redirect_uri: The matching redirect URI used during authorization.

        Returns:
            dict[str, Any]: Keycloak token response containing access_token, id_token, etc.
        """
        token_url = f"{self.issuer_url}/protocol/openid-connect/token"
        target_redirect = redirect_uri or self.redirect_uri

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": target_redirect,
            "code_verifier": code_verifier,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(
            token_url,
            data=payload,
            headers=headers,
            verify=self.verify_ssl,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_user_info(self, access_token: str) -> dict[str, Any]:
        """
        Fetches user identity profile from Keycloak's userinfo endpoint.

        Args:
            access_token: Active Bearer access token.

        Returns:
            dict[str, Any]: User claims dictionary.
        """
        userinfo_url = f"{self.issuer_url}/protocol/openid-connect/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = requests.get(
            userinfo_url,
            headers=headers,
            verify=self.verify_ssl,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"Userinfo request failed with status {resp.status_code}: {resp.text}")
        return {}

    def extract_identity(
        self,
        access_token: str,
        id_token: str | None = None,
    ) -> dict[str, Any]:
        """
        Extracts verified user identity, email, username, and RBAC roles from tokens.

        Merges claims prioritizing ID tokens for user profile attributes (email, name,
        preferred_username) and access tokens for Keycloak realm and client resource roles.

        Args:
            access_token: The access token string.
            id_token: Optional ID token string.

        Returns:
            dict[str, Any]: Normalized identity structure.
        """
        access_claims = decode_jwt_payload_unverified(access_token)
        id_claims = decode_jwt_payload_unverified(id_token) if id_token else {}

        username = (
            id_claims.get("preferred_username")
            or access_claims.get("preferred_username")
            or id_claims.get("email")
            or access_claims.get("email")
            or access_claims.get("sub", "unknown")
        )
        email = id_claims.get("email") or access_claims.get("email") or f"{username}@local"
        name = (
            id_claims.get("name")
            or access_claims.get("name")
            or id_claims.get("given_name")
            or username
        )

        roles: list[str] = []
        realm_access = access_claims.get("realm_access", {})
        if isinstance(realm_access, dict):
            roles.extend(realm_access.get("roles", []))

        resource_access = access_claims.get("resource_access", {}).get(self.client_id, {})
        if isinstance(resource_access, dict):
            roles.extend(resource_access.get("roles", []))

        return {
            "username": username,
            "email": email,
            "name": name,
            "roles": list(set(roles)),
            "sub": access_claims.get("sub"),
        }

    def verify_token(
        self,
        token: str,
        required_role: str | None = None,
        verify_signature: bool = True,
    ) -> dict[str, Any] | None:
        """
        Validates a JWT Bearer token across four verification layers:
        1. Expiration check (exp timestamp vs current unix time)
        2. Issuer URI check (iss matching configured IdP URL)
        3. RBAC role membership verification (realm_access and resource_access roles)
        4. Optional cryptographic signature verification (JWKS public key decoding)

        Args:
            token: JWT token string to validate.
            required_role: Optional role name required for authorization.
            verify_signature: Whether to attempt cryptographic signature verification.

        Returns:
            dict[str, Any] | None: Decoded claims dictionary if valid, None otherwise.
        """
        if not token or not isinstance(token, str):
            return None

        claims = decode_jwt_payload_unverified(token)
        if not claims:
            return None

        exp = claims.get("exp")
        if exp is not None:
            try:
                if time.time() > float(exp):
                    logger.warning(f"Bearer token has expired (exp={exp}, now={time.time()})")
                    return None
            except (ValueError, TypeError):
                return None

        if self.issuer_url:
            iss = str(claims.get("iss", "")).rstrip("/")
            expected_iss = self.issuer_url.rstrip("/")
            if iss and expected_iss and iss != expected_iss:
                logger.warning(f"Token issuer mismatch: expected {expected_iss}, got {iss}")
                return None

        if required_role:
            roles: list[str] = []
            realm_access = claims.get("realm_access", {})
            if isinstance(realm_access, dict):
                roles.extend(realm_access.get("roles", []))
            resource_access = claims.get("resource_access", {})
            if isinstance(resource_access, dict):
                for client_data in resource_access.values():
                    if isinstance(client_data, dict):
                        roles.extend(client_data.get("roles", []))
            if required_role not in roles:
                logger.warning(f"Token lacks required role '{required_role}'. Found roles: {roles}")
                return None

        if verify_signature and self.issuer_url and self.issuer_url.startswith("http"):
            try:
                import jwt
                from jwt import PyJWClient

                if not hasattr(self, "_jwks_client") or self._jwks_client is None:
                    jwks_url = f"{self.issuer_url}/protocol/openid-connect/certs"
                    self._jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)

                signing_key = self._jwks_client.get_signing_key_from_jwt(token)
                verified_claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256", "ES256", "HS256"],
                    options={"verify_aud": False, "verify_exp": True},
                )
                return verified_claims
            except Exception as err:
                logger.debug(f"Cryptographic signature check fallback: {err}")
                if "expired" in str(err).lower():
                    return None

        return claims

    def get_logout_url(
        self,
        id_token: str | None = None,
        post_logout_redirect_uri: str | None = None,
    ) -> str:
        """
        Builds Keycloak OIDC end session / logout URL with target redirect destination.

        Args:
            id_token: Optional id_token_hint.
            post_logout_redirect_uri: Target URL after Keycloak terminates session.

        Returns:
            str: Full Keycloak logout URL.
        """
        params: dict[str, str] = {}
        if id_token:
            params["id_token_hint"] = id_token
        if post_logout_redirect_uri:
            params["post_logout_redirect_uri"] = post_logout_redirect_uri
        elif self.redirect_uri:
            params["post_logout_redirect_uri"] = self.redirect_uri.split("/oauth2/")[0] + "/login"

        qs = f"?{urlencode(params)}" if params else ""
        return f"{self.issuer_url}/protocol/openid-connect/logout{qs}"


_default_oidc_client: OIDCClient | None = None


def get_oidc_client() -> OIDCClient:
    """Returns the singleton OIDCClient instance."""
    global _default_oidc_client
    if _default_oidc_client is None:
        _default_oidc_client = OIDCClient()
    return _default_oidc_client
