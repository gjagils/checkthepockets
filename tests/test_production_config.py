"""Production configuration must fail closed."""
import os
import subprocess
import sys


def _validate(env):
    code = "from app.config import validate_production_config; validate_production_config()"
    return subprocess.run([sys.executable, "-c", code], env={**os.environ, **env}, capture_output=True, text=True)


def test_production_rejects_default_secret_and_http(monkeypatch):
    result = _validate({"ENVIRONMENT": "production", "SECRET_KEY": "change-me-in-production", "APP_URL": "http://localhost:8000", "COOKIE_SECURE": "false"})
    assert result.returncode != 0
    assert "Unsafe production configuration" in result.stderr


def test_production_accepts_strong_https_configuration(monkeypatch):
    result = _validate({"ENVIRONMENT": "production", "SECRET_KEY": "a" * 32, "APP_URL": "https://example.test", "COOKIE_SECURE": "true"})
    assert result.returncode == 0, result.stderr
