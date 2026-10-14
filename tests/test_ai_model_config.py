"""AI-suggesties gebruiken het geconfigureerde model (het hardcoded sonnet-4 gaf in productie een 404)."""
import sys
import types

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
    fake = types.SimpleNamespace(Anthropic=lambda api_key: types.SimpleNamespace(messages=_Messages(seen)))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setattr(ai_suggest, "ANTHROPIC_API_KEY", "test-key")

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
