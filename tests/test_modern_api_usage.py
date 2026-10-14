"""ACT-38a: geen verouderde Starlette/FastAPI-aanroepen meer (TemplateResponse met naam eerst, on_event)."""
import ast
import os
import pathlib
import tempfile

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

import app.main as main


def test_template_response_always_gets_the_request_first():
    """Starlette 1.0 verwijdert de oude signatuur `TemplateResponse("naam", {...})`."""
    offenders = []
    for path in pathlib.Path("app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "TemplateResponse" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_no_on_event_handlers_left():
    assert "on_event(" not in pathlib.Path("app/main.py").read_text()


def test_lifespan_starts_and_stops_the_scheduler(monkeypatch):
    calls = []

    class FakeScheduler:
        running = True

        def shutdown(self, wait=True):
            calls.append(("shutdown", wait))

    monkeypatch.setattr(main, "start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr(main, "background_scheduler", FakeScheduler())
    with TestClient(main.app):
        assert calls == ["start"]
    assert calls == ["start", ("shutdown", False)]
