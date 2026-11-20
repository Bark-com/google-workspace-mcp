"""Bark: WIF+DWD startup refuses unsafe configurations (main.validate_wif_dwd_startup)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Keep these tests independent of a developer's local .env, which main loads.
os.environ["MCP_ENABLE_OAUTH21"] = "false"
os.environ["WORKSPACE_MCP_STATELESS_MODE"] = "false"

import main  # noqa: E402
from auth.oauth_config import reload_oauth_config  # noqa: E402
from core.utils import local_file_access_enabled  # noqa: E402

SA_EMAIL = "sa@project.iam.gserviceaccount.com"


class _FatalExit(Exception):
    pass


class _RecordingUI:
    def __init__(self):
        self.lines = []

    def step(self, *parts):
        self.lines.append(("step", parts))

    def detail(self, *parts):
        self.lines.append(("detail", parts))


@pytest.fixture
def wif(monkeypatch, tmp_path):
    config_file = tmp_path / "wif-config.json"
    config_file.write_text('{"type": "external_account"}')
    for name in (
        "GOOGLE_SERVICE_ACCOUNT_KEY_FILE",
        "GOOGLE_SERVICE_ACCOUNT_KEY_JSON",
        "TRUST_GATEWAY_IDENTITY",
        "MCP_ENABLE_OAUTH21",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(config_file))
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", SA_EMAIL)
    monkeypatch.setenv("DWD_ALLOWED_DOMAINS", "bark.com")
    monkeypatch.setenv("WORKSPACE_MCP_STATELESS_MODE", "true")

    def fake_fatal(ui, text, *details):
        raise _FatalExit(text)

    monkeypatch.setattr(main, "fatal", fake_fatal)
    reload_oauth_config()
    yield monkeypatch
    monkeypatch.undo()
    reload_oauth_config()


def test_wif_startup_accepts_loopback_with_allowlist(wif):
    ui = _RecordingUI()

    main.validate_wif_dwd_startup(ui, "streamable-http", "127.0.0.1")

    assert ("step", ("WIF + DWD mode enabled", "Workload Identity Federation")) in (
        ui.lines
    )


@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5", "::"])
def test_wif_startup_refuses_non_loopback_bind(wif, host):
    with pytest.raises(_FatalExit, match="loopback"):
        main.validate_wif_dwd_startup(_RecordingUI(), "streamable-http", host)


def test_wif_startup_refuses_empty_domain_allowlist(wif):
    wif.delenv("DWD_ALLOWED_DOMAINS")
    reload_oauth_config()

    with pytest.raises(_FatalExit, match="DWD_ALLOWED_DOMAINS"):
        main.validate_wif_dwd_startup(_RecordingUI(), "streamable-http", "127.0.0.1")


def test_wif_startup_refuses_missing_credentials_config(wif, tmp_path):
    wif.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "missing.json"))
    reload_oauth_config()

    with pytest.raises(_FatalExit, match="credentials config not found"):
        main.validate_wif_dwd_startup(_RecordingUI(), "streamable-http", "127.0.0.1")


def test_wif_stateless_mode_hides_local_file_access(wif):
    """file_path parameters stay hidden: stateless WIF never reads server files."""
    assert local_file_access_enabled() is False


def test_credential_rows_show_wif_settings(wif):
    names = [name for name, _, _ in main.describe_credential_config()]

    assert "GOOGLE_APPLICATION_CREDENTIALS" in names
    assert "GOOGLE_SERVICE_ACCOUNT_EMAIL" in names
