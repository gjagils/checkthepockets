"""Tests voor app/move_parser.py — parse Move.nl listing HTML."""
from pathlib import Path

import pytest

from app.move_parser import (
    MoveParseError,
    is_move_url,
    parse_move_html,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_is_move_url_accepts_move_nl():
    assert is_move_url("https://move.nl/exchange-object/abc/overzicht")
    assert is_move_url("https://www.move.nl/foo")


def test_is_move_url_rejects_other_hosts():
    assert not is_move_url("https://www.funda.nl/koop/")
    assert not is_move_url("https://example.com")
    assert not is_move_url("")
    assert not is_move_url("not a url")


def test_parse_move_html_extracts_scenario_fields():
    html = _fixture("move_beemdgrassingel.html")
    result = parse_move_html("https://move.nl/exchange-object/xyz/overzicht", html)

    assert result["name"] == "Beemdgrassingel 26, Vleuten"
    assert result["offer"] == 1_100_000
    assert result["energy_label"] == "A"
    assert result["photo_url"] and result["photo_url"].startswith("http")
    notes = result["notes"] or ""
    assert "Woonoppervlakte: 221 m²" in notes
    assert "Perceel: 417 m²" in notes
    assert "Kamers: 5" in notes


def test_parse_move_html_raises_when_empty():
    with pytest.raises(MoveParseError):
        parse_move_html("https://move.nl/x", "<html><body></body></html>")
