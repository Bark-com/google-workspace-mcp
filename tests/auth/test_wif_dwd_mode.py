"""Tests for Bark WIF+DWD mode (keyless Workload Identity Federation + DWD)."""

import importlib
from types import SimpleNamespace

import pytest

import auth.service_decorator as service_decorator
from auth.oauth_config import OAuthConfig, is_wif_dwd_mode
from auth.service_decorator import GoogleAuthenticationError

WIF_CREDS = "/etc/wif/config.json"
SA_EMAIL = "sa@project.iam.gserviceaccount.com"
_SA_ENV = (
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_SERVICE_ACCOUNT_EMAIL",
    "GOOGLE_SERVICE_ACCOUNT_KEY_FILE",
    "GOOGLE_SERVICE_ACCOUNT_KEY_JSON",
    "MCP_ENABLE_OAUTH21",
    "WORKSPACE_MCP_STATELESS_MODE",
    "TRUST_GATEWAY_IDENTITY",
    "DWD_ALLOWED_DOMAINS",
    "USER_GOOGLE_EMAIL",
)


@pytest.fixture
def wif_env(monkeypatch):
    for name in _SA_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", WIF_CREDS)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", SA_EMAIL)
    return monkeypatch


# --- mode detection ---


def test_is_wif_dwd_mode_true_when_all_wif_vars_set(wif_env):
    assert is_wif_dwd_mode() is True


@pytest.mark.parametrize(
    "key_var", ["GOOGLE_SERVICE_ACCOUNT_KEY_FILE", "GOOGLE_SERVICE_ACCOUNT_KEY_JSON"]
)
def test_is_wif_dwd_mode_false_when_key_configured(wif_env, key_var):
    """A service account key means traditional DWD, not WIF."""
    wif_env.setenv(key_var, "/etc/sa/key.json")
    assert is_wif_dwd_mode() is False


@pytest.mark.parametrize(
    "missing", ["GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_SERVICE_ACCOUNT_EMAIL"]
)
def test_is_wif_dwd_mode_false_when_a_wif_var_is_missing(wif_env, missing):
    wif_env.delenv(missing)
    assert is_wif_dwd_mode() is False


def test_is_wif_dwd_mode_false_when_neither_wif_var_set(monkeypatch):
    for name in _SA_ENV:
        monkeypatch.delenv(name, raising=False)
    assert is_wif_dwd_mode() is False


# --- OAuthConfig ---


def test_config_enables_service_account_and_stateless_in_wif_mode(wif_env):
    wif_env.setenv("WORKSPACE_MCP_STATELESS_MODE", "true")
    wif_env.setenv("DWD_ALLOWED_DOMAINS", "Bark.com")
    config = OAuthConfig()
    assert config.wif_dwd_mode is True
    assert config.is_service_account_enabled() is True
    assert config.stateless_mode is True
    assert config.dwd_allowed_domains == ["bark.com"]


def test_config_still_rejects_stateless_without_oauth21_outside_wif(monkeypatch):
    for name in _SA_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WORKSPACE_MCP_STATELESS_MODE", "true")
    with pytest.raises(ValueError, match="WORKSPACE_MCP_STATELESS_MODE"):
        OAuthConfig()


def test_config_rejects_wif_with_trusted_gateway(wif_env):
    wif_env.setenv("TRUST_GATEWAY_IDENTITY", "true")
    wif_env.setenv("GATEWAY_IDENTITY_JWKS_URL", "https://gateway.example/jwks")
    wif_env.setenv("GATEWAY_IDENTITY_AUDIENCE", "workspace-mcp")
    with pytest.raises(ValueError, match="incompatible with TRUST_GATEWAY_IDENTITY"):
        OAuthConfig()


def test_core_config_disables_user_google_email_in_wif_mode(wif_env):
    import core.config as core_config

    wif_env.setenv("USER_GOOGLE_EMAIL", "default@bark.com")
    try:
        assert importlib.reload(core_config).USER_GOOGLE_EMAIL is None
    finally:
        wif_env.delenv("GOOGLE_APPLICATION_CREDENTIALS")
        wif_env.delenv("USER_GOOGLE_EMAIL")
        importlib.reload(core_config)


# --- credentials ---


def test_configured_user_email_is_ignored_in_wif_mode(wif_env):
    wif_env.setenv("USER_GOOGLE_EMAIL", "default@bark.com")
    wif_env.setattr(service_decorator, "_ENV_USER_EMAIL", "default@bark.com")
    assert service_decorator._get_configured_user_google_email() is None


def test_wif_credentials_impersonate_sa_with_dwd_subject(wif_env):
    source = object()
    calls = {}

    def fake_default(scopes):
        calls["default_scopes"] = scopes
        return source, "project"

    def fake_impersonated(**kwargs):
        calls["impersonated"] = kwargs
        return "impersonated-creds"

    wif_env.setattr(service_decorator.google_auth, "default", fake_default)
    wif_env.setattr(
        service_decorator.google_impersonated_credentials,
        "Credentials",
        fake_impersonated,
    )
    wif_env.setattr(
        service_decorator,
        "get_oauth_config",
        lambda: SimpleNamespace(
            service_account_key_file=None, service_account_key_json=None
        ),
    )

    creds = service_decorator._get_service_account_credentials(
        ["https://www.googleapis.com/auth/drive"], "user@bark.com"
    )

    assert creds == "impersonated-creds"
    assert calls["default_scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]
    assert calls["impersonated"]["source_credentials"] is source
    assert calls["impersonated"]["target_principal"] == SA_EMAIL
    assert calls["impersonated"]["target_scopes"] == [
        "https://www.googleapis.com/auth/drive"
    ]
    assert calls["impersonated"]["subject"] == "user@bark.com"


# --- DWD subject selection ---


def _patch_wif_authentication(monkeypatch, *, allowed_domains=("bark.com",)):
    monkeypatch.setattr(service_decorator, "is_service_account_enabled", lambda: True)
    monkeypatch.setattr(
        service_decorator,
        "get_oauth_config",
        lambda: SimpleNamespace(
            service_account_key_file=None,
            service_account_key_json=None,
            dwd_allowed_domains=list(allowed_domains),
        ),
    )

    async def gateway_must_not_be_used(*args, **kwargs):
        raise AssertionError("WIF mode must not consult the gateway principal")

    monkeypatch.setattr(
        service_decorator, "get_verified_gateway_principal", gateway_must_not_be_used
    )
    captured = {}
    fake_service = object()

    def fake_get_creds(scopes, subject):
        captured["scopes"] = scopes
        captured["subject"] = subject
        return object()

    monkeypatch.setattr(
        service_decorator, "_get_service_account_credentials", fake_get_creds
    )
    monkeypatch.setattr(
        service_decorator, "build_google_service", lambda *args: fake_service
    )
    return captured, fake_service


async def _authenticate(email, tool_name="search_drive_files", scopes=None):
    return await service_decorator._authenticate_service(
        use_oauth21=False,
        service_name="drive",
        service_version="v3",
        tool_name=tool_name,
        user_google_email=email,
        resolved_scopes=scopes or ["https://www.googleapis.com/auth/drive.readonly"],
        mcp_session_id=None,
        authenticated_user=None,
    )


@pytest.mark.asyncio
async def test_wif_subject_is_the_caller_email(wif_env):
    wif_env.setenv("USER_GOOGLE_EMAIL", "default@bark.com")
    captured, fake_service = _patch_wif_authentication(wif_env)

    service, actual_user = await _authenticate("Alice@Bark.com")

    assert service is fake_service
    assert actual_user == "alice@bark.com"
    assert captured["subject"] == "alice@bark.com"


@pytest.mark.asyncio
async def test_wif_widens_drive_file_scope_like_upstream_dwd(wif_env):
    captured, _ = _patch_wif_authentication(wif_env)

    await _authenticate(
        "alice@bark.com",
        tool_name="create_drive_file",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )

    assert "https://www.googleapis.com/auth/drive" in captured["scopes"]
    assert "https://www.googleapis.com/auth/drive.file" not in captured["scopes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("email", [None, "", "not-an-email"])
async def test_wif_requires_a_valid_caller_email(wif_env, email):
    wif_env.setenv("USER_GOOGLE_EMAIL", "default@bark.com")
    captured, _ = _patch_wif_authentication(wif_env)

    with pytest.raises(GoogleAuthenticationError, match="user_google_email"):
        await _authenticate(email)
    assert "subject" not in captured


@pytest.mark.asyncio
async def test_wif_rejects_subject_outside_allowed_domains(wif_env):
    captured, _ = _patch_wif_authentication(wif_env)

    with pytest.raises(GoogleAuthenticationError, match="DWD_ALLOWED_DOMAINS"):
        await _authenticate("mallory@example.com")
    assert "subject" not in captured


@pytest.mark.asyncio
async def test_wif_fails_closed_without_allowed_domains(wif_env):
    captured, _ = _patch_wif_authentication(wif_env, allowed_domains=())

    with pytest.raises(GoogleAuthenticationError, match="DWD_ALLOWED_DOMAINS"):
        await _authenticate("alice@bark.com")
    assert "subject" not in captured
