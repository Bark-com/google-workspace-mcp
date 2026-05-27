"""Tests for WIF+DWD mode detection (is_wif_dwd_mode)."""

from types import SimpleNamespace

import auth.oauth_config as oauth_config_module
from auth.oauth_config import is_wif_dwd_mode

WIF_CREDS = "/etc/wif/config.json"
SA_EMAIL = "sa@project.iam.gserviceaccount.com"


def _fake_config(*, key_file=None, key_json=None):
    return SimpleNamespace(
        service_account_key_file=key_file,
        service_account_key_json=key_json,
    )


def test_is_wif_dwd_mode_true_when_all_wif_vars_set(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", WIF_CREDS)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", SA_EMAIL)
    monkeypatch.setattr(oauth_config_module, "get_oauth_config", lambda: _fake_config())

    assert is_wif_dwd_mode() is True


def test_is_wif_dwd_mode_false_when_key_file_present(monkeypatch):
    """Traditional SA key file means this is not WIF mode."""
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", WIF_CREDS)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", SA_EMAIL)
    monkeypatch.setattr(
        oauth_config_module,
        "get_oauth_config",
        lambda: _fake_config(key_file="/etc/sa/key.json"),
    )

    assert is_wif_dwd_mode() is False


def test_is_wif_dwd_mode_false_when_key_json_present(monkeypatch):
    """Inline SA key JSON means this is not WIF mode."""
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", WIF_CREDS)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", SA_EMAIL)
    monkeypatch.setattr(
        oauth_config_module,
        "get_oauth_config",
        lambda: _fake_config(key_json='{"type": "service_account"}'),
    )

    assert is_wif_dwd_mode() is False


def test_is_wif_dwd_mode_false_without_google_application_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", SA_EMAIL)
    monkeypatch.setattr(oauth_config_module, "get_oauth_config", lambda: _fake_config())

    assert is_wif_dwd_mode() is False


def test_is_wif_dwd_mode_false_without_service_account_email(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", WIF_CREDS)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", raising=False)
    monkeypatch.setattr(oauth_config_module, "get_oauth_config", lambda: _fake_config())

    assert is_wif_dwd_mode() is False


def test_is_wif_dwd_mode_false_when_neither_wif_var_set(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", raising=False)
    monkeypatch.setattr(oauth_config_module, "get_oauth_config", lambda: _fake_config())

    assert is_wif_dwd_mode() is False
