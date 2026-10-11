"""
Login blueprint for the Py Phone Caller UI.

Handles user authentication with dual support for local Piccolo database credentials
and standard OpenID Connect (OIDC) Single Sign-On via Keycloak / OAuth2.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime

from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_login import login_user
import itsdangerous

from py_phone_caller_utils.auth.oidc import generate_pkce_pair, get_oidc_client
from py_phone_caller_utils.config import settings
from py_phone_caller_utils.login.user import User
from py_phone_caller_utils.py_phone_caller_db.db_user import (
    check_user_password,
    generate_complex_password,
    insert_user,
    is_legacy_password_hash,
    select_user,
    update_password,
)
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    Users,
)
from py_phone_caller_ui.constants import UI_ADMIN_USER, UI_SECRET_KEY

HOME_TEMPLATE = "home_blueprint.home"
LOGIN_TEMPLATE = "login.html"

login_blueprint = Blueprint(
    "login_blueprint",
    __name__,
    template_folder="templates/login",
)


def _get_state_serializer() -> itsdangerous.URLSafeTimedSerializer:
    """Returns a serializer to cryptographically sign and verify OIDC state parameters."""
    secret = UI_SECRET_KEY or "py-phone-caller-oauth2-state-fallback-secret"
    return itsdangerous.URLSafeTimedSerializer(secret, salt="oidc-flow-state")


def _get_redirect_uri() -> str:
    """
    Computes the expected OAuth2 redirect URI taking gateway and reverse proxies into account.

    Detects client entrypoints via standard proxy headers (X-Forwarded-Proto, X-Forwarded-Host),
    resolves dedicated APISIX ingress gateway ports, and falls back to configured application URLs.
    """
    forwarded_proto = (
        request.headers.get("X-Forwarded-Proto")
        or request.environ.get("wsgi.url_scheme")
        or request.scheme
    )
    forwarded_host = (
        request.headers.get("X-Forwarded-Host")
        or request.headers.get("Host")
        or request.host
    )

    gateway_cfg = getattr(settings, "gateway", {})
    behind_gateway = getattr(gateway_cfg, "behind_gateway", False)
    gateway_url = getattr(gateway_cfg, "gateway_public_url", "")

    if forwarded_host:
        host_clean = forwarded_host.split(",")[0].strip()
        if ":9080" in host_clean or host_clean.endswith("9080"):
            return f"http://{host_clean}/oauth2/callback"
        if ":9443" in host_clean or host_clean.endswith("9443"):
            return f"https://{host_clean}/oauth2/callback"
        if ":5000" in host_clean or host_clean.endswith("5000"):
            return f"{forwarded_proto}://{host_clean}/oauth2/callback"

    if behind_gateway and gateway_url:
        return f"{gateway_url.rstrip('/')}/oauth2/callback"

    oauth_cfg = getattr(getattr(settings, "auth", None), "oauth2", {})
    configured_uri = getattr(oauth_cfg, "redirect_uri", None)
    if configured_uri:
        return configured_uri

    return url_for("login_blueprint.oauth2_callback", _external=True)


@login_blueprint.route("/login", methods=["GET", "POST"])
async def login():
    """
    Handles the login process, supporting local credentials and OIDC SSO.
    """
    auth_cfg = getattr(settings, "auth", {})
    provider = getattr(auth_cfg, "provider", "local")
    oauth_cfg = getattr(auth_cfg, "oauth2", {})
    oauth2_enabled = provider == "oauth2" or getattr(oauth_cfg, "enabled", False)
    local_fallback_enabled = getattr(auth_cfg, "local_fallback_enabled", True)

    if request.method == "POST":
        form_email = request.form.get("email") or ""
        form_password = request.form.get("password") or ""

        if not form_email or not form_password:
            logging.info("Login attempt failed: Missing email or password.")
            return render_template(
                LOGIN_TEMPLATE,
                home_url=url_for(HOME_TEMPLATE),
                oauth2_enabled=oauth2_enabled,
                oauth2_login_url=url_for("login_blueprint.oauth2_login"),
                local_fallback_enabled=local_fallback_enabled,
                error="Invalid username or password",
            )

        user_from_db = await select_user(form_email)

        if not user_from_db:
            logging.info(f"Login attempt failed: User '{form_email}' not found.")
            return render_template(
                LOGIN_TEMPLATE,
                home_url=url_for(HOME_TEMPLATE),
                oauth2_enabled=oauth2_enabled,
                oauth2_login_url=url_for("login_blueprint.oauth2_login"),
                local_fallback_enabled=local_fallback_enabled,
                error="Invalid username or password",
            )

        if not user_from_db.get("is_active", True):
            logging.info(f"Login attempt blocked: User '{form_email}' is disabled.")
            return render_template(
                LOGIN_TEMPLATE,
                home_url=url_for(HOME_TEMPLATE),
                oauth2_enabled=oauth2_enabled,
                oauth2_login_url=url_for("login_blueprint.oauth2_login"),
                local_fallback_enabled=local_fallback_enabled,
                error="Account is disabled. Please contact an administrator.",
            )

        roles = (
            ["alert-admin"]
            if form_email.lower() == str(UI_ADMIN_USER).lower()
            else ["alert-operator"]
        )
        current_user = User(
            username=user_from_db.get("email"),
            roles=roles,
            email=user_from_db.get("email"),
            id=str(user_from_db.get("id")),
        )
        stored_password_hash = user_from_db.get("password")

        if check_user_password(stored_password_hash, form_password):
            if is_legacy_password_hash(stored_password_hash):
                await update_password(form_email, form_password)

            session["roles"] = roles
            session["auth_provider"] = "local"
            login_user(current_user)
            await Users.update(
                {Users.last_login: datetime.now(UTC).replace(tzinfo=None)}
            ).where(Users.email == form_email)
            return redirect(url_for(HOME_TEMPLATE))
        else:
            logging.info(f"Invalid password attempt for user '{form_email}'.")
            return render_template(
                LOGIN_TEMPLATE,
                home_url=url_for(HOME_TEMPLATE),
                oauth2_enabled=oauth2_enabled,
                oauth2_login_url=url_for("login_blueprint.oauth2_login"),
                local_fallback_enabled=local_fallback_enabled,
                error="Invalid username or password",
            )

    if (
        oauth2_enabled
        and not local_fallback_enabled
        and request.args.get("local") != "true"
    ):
        return redirect(url_for("login_blueprint.oauth2_login"))

    error_msg = request.args.get("error")
    return render_template(
        LOGIN_TEMPLATE,
        home_url=url_for(HOME_TEMPLATE),
        oauth2_enabled=oauth2_enabled,
        oauth2_login_url=url_for("login_blueprint.oauth2_login"),
        local_fallback_enabled=local_fallback_enabled,
        error=error_msg,
    )


@login_blueprint.route("/oauth2/login")
def oauth2_login():
    """
    Initiates PKCE OIDC authorization flow by redirecting to Keycloak.

    Generates a cryptographically random PKCE code verifier and S256 challenge,
    packs the verifier and expected redirect URI into a tamper-proof signed state token,
    and sets fallback session/cookie variables before redirecting the client to the IdP.
    """
    oidc = get_oidc_client()
    if not oidc.is_configured:
        return redirect(
            url_for("login_blueprint.login", error="OIDC provider is not configured")
        )

    code_verifier, code_challenge = generate_pkce_pair()
    redirect_uri = _get_redirect_uri()

    state_payload = {
        "verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "nonce": secrets.token_hex(16),
    }
    state = _get_state_serializer().dumps(state_payload)

    session["oauth2_state"] = state
    session["oauth2_verifier"] = code_verifier
    session["oauth2_redirect_uri"] = redirect_uri

    auth_url = oidc.get_authorization_url(
        state=state,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
    )
    resp = redirect(auth_url)
    resp.set_cookie(
        "oauth2_verifier",
        code_verifier,
        max_age=600,
        httponly=True,
        samesite="Lax",
        path="/oauth2",
    )
    return resp


@login_blueprint.route("/oauth2/callback")
async def oauth2_callback():
    """
    Handles the OIDC authorization code callback, exchanging code for tokens.

    Validates signed state parameter with cookie and session fallbacks, exchanges
    authorization code and PKCE verifier for JWT tokens, auto-provisions or links
    the user record in the local database for audit trail foreign keys, and establishes
    the authenticated user session with RBAC role assignments.
    """
    if request.args.get("error"):
        error_desc = request.args.get("error_description", "Authentication failed")
        return redirect(url_for("login_blueprint.login", error=error_desc))

    code = request.args.get("code")
    received_state = request.args.get("state")

    code_verifier = None
    redirect_uri = None

    if received_state:
        try:
            state_data = _get_state_serializer().loads(received_state, max_age=600)
            code_verifier = state_data.get("verifier")
            redirect_uri = state_data.get("redirect_uri")
            logging.info("Successfully validated signed OIDC state token from Keycloak redirect.")
        except itsdangerous.BadSignature as sig_err:
            logging.warning(f"Signed OIDC state token validation failed: {sig_err}")

    if not code_verifier:
        stored_state = session.pop("oauth2_state", None)
        if stored_state and stored_state == received_state:
            code_verifier = session.pop("oauth2_verifier", None)
            redirect_uri = session.pop("oauth2_redirect_uri", None)

    if not code_verifier:
        code_verifier = request.cookies.get("oauth2_verifier")

    if not redirect_uri:
        redirect_uri = _get_redirect_uri()

    if not code or not code_verifier:
        logging.warning(
            f"OIDC validation failed: code={bool(code)}, code_verifier={bool(code_verifier)}"
        )
        return redirect(
            url_for("login_blueprint.login", error="Invalid authentication session or state mismatch")
        )

    oidc = get_oidc_client()

    try:
        token_data = oidc.exchange_code_for_token(
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
    except Exception as err:
        logging.error(f"Failed to exchange authorization code for tokens: {err}")
        return redirect(
            url_for("login_blueprint.login", error="Failed to authenticate with Identity Provider")
        )

    access_token = token_data.get("access_token", "")
    id_token = token_data.get("id_token")
    identity = oidc.extract_identity(access_token=access_token, id_token=id_token)

    email = identity.get("email") or f"{identity.get('username')}@openalert.lan"
    username = identity.get("username") or email
    name = identity.get("name") or username
    roles = identity.get("roles", [])

    user_record = await select_user(email)
    if not user_record:
        logging.info(f"First-time SSO login: provisioning local user record for '{email}'")
        await insert_user(
            given_name=name,
            email=email,
            password=generate_complex_password(32),
        )
        user_record = await select_user(email)

    user_id = str(user_record.get("id")) if user_record else None

    session["roles"] = roles
    session["auth_provider"] = "oauth2"
    if id_token:
        session["id_token"] = id_token

    current_user = User(
        username=email,
        roles=roles,
        email=email,
        id=user_id,
    )
    login_user(current_user)

    await Users.update(
        {Users.last_login: datetime.now(UTC).replace(tzinfo=None)}
    ).where(Users.email == email)

    logging.info(f"OIDC user '{email}' successfully logged in with roles {roles}")
    resp = redirect(url_for(HOME_TEMPLATE))
    resp.delete_cookie("oauth2_verifier", path="/oauth2")
    return resp
