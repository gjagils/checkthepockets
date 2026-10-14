"""AI-suggesties gebruiken het geconfigureerde model (het hardcoded sonnet-4 gaf in productie een 404)."""
import sys
import types

import app.ai_client as ai_client
import app.ai_suggest as ai_suggest
from app.config import ANTHROPIC_MODEL


class _Messages:
    def __init__(self, seen):
        self.seen = seen

    def create(self, **kwargs):
        self.seen.append(kwargs["model"])
        raise RuntimeError("stop na het vastleggen van het model")


def test_every_ai_call_uses_the_configured_model(monkeypatch):
    seen = []
    fake = types.SimpleNamespace(Anthropic=lambda api_key, **kwargs: types.SimpleNamespace(messages=_Messages(seen)))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setattr(ai_suggest, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai_client, "ANTHROPIC_API_KEY", "test-key")

    cats = [{"id": 1, "name": "Boodschappen"}]
    ai_suggest.suggest_rule("AH AMSTERDAM", "Albert Heijn", cats)
    group = {"merchant": "AH", "match_value": "AH", "uncat_count": 3, "cat_count": 1,
             "sample_descriptions": ["AH AMSTERDAM"]}
    ai_suggest.suggest_rules_bulk([group], [{"id": 1, "name": "Boodschappen", "parent_name": "Huishouden"}])
    assert seen and set(seen) == {ANTHROPIC_MODEL}


def test_no_retired_model_name_is_hardcoded():
    import pathlib
    for path in pathlib.Path("app").rglob("*.py"):
        assert "claude-sonnet-4-20250514" not in path.read_text(), path


def test_call_json_strips_fences_sets_a_timeout_and_parses(monkeypatch):
    captured = {}

    class Messages:
        def create(self, **kwargs):
            captured["model"] = kwargs["model"]
            reply = types.SimpleNamespace(text='```json\n{"ok": true, "n": 3}\n```')
            return types.SimpleNamespace(content=[reply])

    def make_client(api_key, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return types.SimpleNamespace(messages=Messages())

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=make_client))
    monkeypatch.setattr(ai_client, "ANTHROPIC_API_KEY", "test-key")
    assert ai_client.call_json("vraag", max_tokens=50) == {"ok": True, "n": 3}
    assert captured == {"model": ANTHROPIC_MODEL, "timeout": ai_client.TIMEOUT_SECONDS}


def test_call_json_without_a_key_raises_ai_unavailable(monkeypatch):
    import pytest

    monkeypatch.setattr(ai_client, "ANTHROPIC_API_KEY", "")
    with pytest.raises(ai_client.AIUnavailable):
        ai_client.call_json("vraag", max_tokens=50)


def test_ai_suggest_has_no_client_code_of_its_own():
    import pathlib
    text = pathlib.Path("app/ai_suggest.py").read_text()
    assert "anthropic." not in text and "messages.create" not in text and "json.loads" not in text
