import importlib
from decimal import Decimal


def _reload_config(monkeypatch, **env):
    # Neutralise the on-disk .env so we test the code's own defaults, not the
    # developer's local file.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    for key in ("FLASK_DEBUG", "SAFETY_BUFFER"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config as config_module

    return importlib.reload(config_module).Config


def test_debug_defaults_false(monkeypatch):
    assert _reload_config(monkeypatch).DEBUG is False


def test_debug_truthy_values(monkeypatch):
    for value in ("true", "True", "1", "yes", "on"):
        assert _reload_config(monkeypatch, FLASK_DEBUG=value).DEBUG is True


def test_debug_falsy_values(monkeypatch):
    for value in ("false", "0", "no", ""):
        assert _reload_config(monkeypatch, FLASK_DEBUG=value).DEBUG is False


def test_safety_buffer_default_is_decimal(monkeypatch):
    cfg = _reload_config(monkeypatch)
    assert isinstance(cfg.SAFETY_BUFFER, Decimal)
    assert cfg.SAFETY_BUFFER == Decimal("2000")


def test_safety_buffer_from_env(monkeypatch):
    cfg = _reload_config(monkeypatch, SAFETY_BUFFER="3500.50")
    assert cfg.SAFETY_BUFFER == Decimal("3500.50")


def test_safety_buffer_bad_env_falls_back(monkeypatch):
    cfg = _reload_config(monkeypatch, SAFETY_BUFFER="not-a-number")
    assert cfg.SAFETY_BUFFER == Decimal("2000")


def teardown_module(module):
    import importlib
    import config

    importlib.reload(config)
