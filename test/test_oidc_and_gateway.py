"""
Unit tests for OIDC Client, PKCE generator, JWT claim extraction,
and RBAC User model integration.
"""

import base64
import hashlib
import json
import pytest
from unittest.mock import MagicMock, patch

from py_phone_caller_utils.auth.oidc import (
    OIDCClient,
    decode_jwt_payload_unverified,
    generate_pkce_pair,
)
from py_phone_caller_utils.login.user import User


class TestPKCEAndJWT:
    def test_generate_pkce_pair(self):
        verifier, challenge = generate_pkce_pair()
        assert len(verifier) >= 43
        assert len(challenge) > 0
        # Verify RFC 7636 S256 transformation
        computed = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        assert challenge == computed

    def test_decode_jwt_payload_unverified(self):
        payload = {
            "sub": "user-123",
            "preferred_username": "tester",
            "email": "tester@openalert.lan",
            "realm_access": {"roles": ["alert-operator", "default-roles"]},
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
        token = f"dummyHeader.{payload_b64}.dummySig"

        decoded = decode_jwt_payload_unverified(token)
        assert decoded["sub"] == "user-123"
        assert decoded["preferred_username"] == "tester"
        assert decoded["realm_access"]["roles"] == ["alert-operator", "default-roles"]

    def test_decode_jwt_payload_malformed(self):
        assert decode_jwt_payload_unverified("invalid-token") == {}
        assert decode_jwt_payload_unverified("") == {}


class TestOIDCClient:
    def test_authorization_url(self):
        client = OIDCClient(
            issuer_url="https://keycloak.lan:8443/realms/py-phone-caller",
            client_id="py-phone-caller-ui",
            redirect_uri="https://keycloak.lan:9443/oauth2/callback",
        )
        assert client.is_configured
        url = client.get_authorization_url(
            state="state123",
            code_challenge="chal456",
        )
        assert "https://keycloak.lan:8443/realms/py-phone-caller/protocol/openid-connect/auth?" in url
        assert "client_id=py-phone-caller-ui" in url
        assert "code_challenge=chal456" in url
        assert "code_challenge_method=S256" in url
        assert "state=state123" in url
        assert "response_type=code" in url

    def test_extract_identity(self):
        client = OIDCClient(
            issuer_url="https://keycloak.lan:8443/realms/py-phone-caller",
            client_id="py-phone-caller-ui",
        )
        access_payload = {
            "sub": "id-999",
            "preferred_username": "operator1",
            "email": "op1@openalert.lan",
            "name": "Operator One",
            "realm_access": {"roles": ["alert-operator", "offline_access"]},
        }
        b64_acc = base64.urlsafe_b64encode(json.dumps(access_payload).encode()).decode().rstrip("=")
        access_token = f"h.{b64_acc}.s"

        ident = client.extract_identity(access_token)
        assert ident["username"] == "operator1"
        assert ident["email"] == "op1@openalert.lan"
        assert ident["name"] == "Operator One"
        assert "alert-operator" in ident["roles"]

    def test_logout_url(self):
        client = OIDCClient(
            issuer_url="https://keycloak.lan:8443/realms/py-phone-caller",
            client_id="py-phone-caller-ui",
            redirect_uri="https://gateway.lan:9443/oauth2/callback",
        )
        logout_url = client.get_logout_url(id_token="id_token_xyz")
        assert "https://keycloak.lan:8443/realms/py-phone-caller/protocol/openid-connect/logout?" in logout_url
        assert "id_token_hint=id_token_xyz" in logout_url


class TestUserRBACModel:
    def test_default_user_backward_compatibility(self):
        user = User(username="admin")
        assert user.username == "admin"
        assert user.is_authenticated
        assert user.is_active
        assert not user.is_anonymous
        assert user.roles == []

    def test_user_rbac_roles(self):
        admin_user = User(username="john", roles=["alert-admin"])
        assert admin_user.has_role("alert-admin")
        assert admin_user.is_admin
        assert admin_user.is_operator
        assert admin_user.is_viewer

        op_user = User(username="jane", roles=["alert-operator"])
        assert not op_user.is_admin
        assert op_user.is_operator
        assert op_user.is_viewer

        view_user = User(username="bob", roles=["alert-viewer"])
        assert not view_user.is_admin
        assert not view_user.is_operator
        assert view_user.is_viewer

class TestM2MTokenVerification:
    def _create_token(self, payload: dict) -> str:
        b64_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return f"header.{b64_payload}.sig"

    def test_verify_token_valid(self):
        client = OIDCClient(issuer_url="https://keycloak.lan:8443/realms/py-phone-caller")
        token = self._create_token({
            "sub": "m2m-service-account",
            "azp": "py-phone-caller-m2m",
            "iss": "https://keycloak.lan:8443/realms/py-phone-caller",
            "exp": 9999999999,
            "realm_access": {"roles": ["alert-operator"]},
        })
        claims = client.verify_token(token, required_role="alert-operator", verify_signature=False)
        assert claims is not None
        assert claims["azp"] == "py-phone-caller-m2m"
        assert claims["sub"] == "m2m-service-account"

    def test_verify_token_expired(self):
        client = OIDCClient(issuer_url="https://keycloak.lan:8443/realms/py-phone-caller")
        token = self._create_token({
            "sub": "m2m-service-account",
            "azp": "py-phone-caller-m2m",
            "iss": "https://keycloak.lan:8443/realms/py-phone-caller",
            "exp": 1000000,  # expired far in past
            "realm_access": {"roles": ["alert-operator"]},
        })
        assert client.verify_token(token, verify_signature=False) is None

    def test_verify_token_missing_role(self):
        client = OIDCClient(issuer_url="https://keycloak.lan:8443/realms/py-phone-caller")
        token = self._create_token({
            "sub": "m2m-service-account",
            "azp": "py-phone-caller-m2m",
            "iss": "https://keycloak.lan:8443/realms/py-phone-caller",
            "exp": 9999999999,
            "realm_access": {"roles": ["default-roles"]},
        })
        # Requires alert-operator, but only has default-roles
        assert client.verify_token(token, required_role="alert-operator", verify_signature=False) is None

    def test_verify_token_issuer_mismatch(self):
        client = OIDCClient(issuer_url="https://keycloak.lan:8443/realms/py-phone-caller")
        token = self._create_token({
            "sub": "m2m-service-account",
            "azp": "py-phone-caller-m2m",
            "iss": "https://rogue-issuer.evil/realms/fake",
            "exp": 9999999999,
            "realm_access": {"roles": ["alert-operator"]},
        })
        assert client.verify_token(token, verify_signature=False) is None

