"""Parser voor Move.nl koop-pagina's.

Alternatief voor Funda: Move.nl blokkeert server-side fetches niet met
captcha en levert een JSON-payload in de HTML waaruit we alle scenario-
velden kunnen halen. Parser is bewust klein gehouden — we halen eruit
wat we nodig hebben voor een nieuw scenario en laten de rest liggen.

Gebruik:

    data = fetch_move(url)  # raised MoveParseError bij problemen

De publieke API en foutmodel zijn gelijk aan die van `funda_parser` zodat
de front-end ze uitwisselbaar kan gebruiken.
"""
from __future__ import annotations

import json
import logging
import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

import requests


log = logging.getLogger(__name__)


class MoveParseError(Exception):
    """Niet-fatale parse-fout: formulier blijft bruikbaar, user vult handmatig."""


_MOVE_HOSTS = {"move.nl", "www.move.nl"}
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_FETCH_TIMEOUT = 10


def is_move_url(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() in _MOVE_HOSTS
    )


# ── Price extraction ────────────────────────────────────────────────────
#
# Move.nl bedt een GraphQL-payload in als JSON-in-JS-string, dus quotes zijn
# dubbel-ge-escaped (`\"`). We unescape de HTML-string voor parsing, zodat de
# patterns eenvoudig blijven.

_PRICE_SHORT_RE = re.compile(
    r'"(?:koop|asking|offering)Price"[^{]*\{[^}]{0,300}?'
    r'"formatMoneyShort"\s*:\s*"€\s*([\d\.]+)',
    re.IGNORECASE,
)
_PRICE_LONG_RE = re.compile(
    r'"(?:koop|asking|offering)Price"[^{]*\{[^}]{0,300}?'
    r'"formatMoneyLong"\s*:\s*"€\s*([\d\.]+)',
    re.IGNORECASE,
)


def _unescape_json_in_js(html: str) -> str:
    """Vervang `\\"` → `"` en `\\/` → `/` in de HTML zodat JSON-keys simpel
    te matchen zijn. Move.nl serveert de payload als `__NUXT__ = JSON.parse("...")`
    dus alle quotes zijn ge-escaped."""
    return html.replace('\\"', '"').replace("\\/", "/")


def _extract_price(html: str) -> int | None:
    clean = _unescape_json_in_js(html)
    for pattern in (_PRICE_SHORT_RE, _PRICE_LONG_RE):
        m = pattern.search(clean)
        if m:
            raw = m.group(1).replace(".", "")
            if raw.isdigit():
                val = int(raw)
                if 10_000 <= val <= 100_000_000:
                    return val

    # Fallback: generic Euro pattern binnen het koopPrice-blok.
    block_match = re.search(
        r'"(?:koop|asking|offering)Price"[^{]*\{[^}]{0,400}', clean,
        re.IGNORECASE,
    )
    if block_match:
        for raw in re.findall(r"€\s*([\d\.]+)", block_match.group(0)):
            digits = raw.replace(".", "")
            if digits.isdigit():
                val = int(digits)
                if 10_000 <= val <= 100_000_000:
                    return val
    return None


# ── Address ─────────────────────────────────────────────────────────────

def _extract_address(html: str) -> tuple[str | None, str | None]:
    """Haal (straat+huisnummer, plaats) uit de JSON-blob of og:title."""
    clean = _unescape_json_in_js(html)
    street = None
    city = None

    # JSON-keys street / houseNumber / city staan vaak los van elkaar.
    street_m = re.search(r'"street"\s*:\s*"([^"]+)"', clean)
    if street_m:
        street = street_m.group(1).strip() or None

    # Move gebruikt "nr": 26, "nrExtension": "" voor huisnummer + toevoeging.
    nr_m = re.search(r'"nr"\s*:\s*(\d+)', clean)
    ext_m = re.search(r'"nrExtension"\s*:\s*"([^"]*)"', clean)
    if nr_m and street:
        street = f"{street} {nr_m.group(1)}"
        if ext_m and ext_m.group(1).strip():
            street = f"{street}{ext_m.group(1).strip()}"

    city_m = re.search(r'"city"\s*:\s*"([^"]+)"', clean)
    if city_m:
        city = city_m.group(1).strip() or None

    # Fallback: og:title is meestal "Straat Nr 1234 AB Plaats".
    if not street or not city:
        og_m = re.search(
            r'<meta\s+property="og:title"\s+content="([^"]+)"', html,
        )
        if og_m:
            title = unescape(og_m.group(1)).strip()
            # Probeer "Straat 26 3452 CW Vleuten " pattern.
            parts = re.match(
                r"^(.+?)\s+(\d{4}\s?[A-Z]{2})\s+(.+?)\s*$", title,
            )
            if parts:
                if not street:
                    street = parts.group(1).strip()
                if not city:
                    city = parts.group(3).strip()

    return street, city


# ── Extras ──────────────────────────────────────────────────────────────

def _extract_summary_facts(html: str) -> list[str]:
    clean = _unescape_json_in_js(html)
    facts: list[str] = []
    m = re.search(r'"woonOppervlakte"\s*:\s*(\d{1,5})', clean)
    if m:
        facts.append(f"Woonoppervlakte: {m.group(1)} m²")
    m = re.search(r'"perceelOppervlakte"\s*:\s*(\d{1,6})', clean)
    if m:
        facts.append(f"Perceel: {m.group(1)} m²")
    m = re.search(r'"aantalKamers"\s*:\s*(\d{1,3})', clean)
    if m:
        facts.append(f"Kamers: {m.group(1)}")
    for key in ("bouwjaar", "buildYear", "yearBuilt", "constructionYear"):
        m = re.search(rf'"{key}"\s*:\s*"?(\d{{4}})"?', clean, re.IGNORECASE)
        if m:
            facts.append(f"Bouwjaar: {m.group(1)}")
            break
    return facts


_ENERGY_DIRECT_RE = re.compile(
    r'"(?:energyLabel|energielabel|definitiefEnergielabel)"\s*:\s*"([A-G][+]*)"',
    re.IGNORECASE,
)
# Move.nl bedt energielabel in als Kenmerk-item:
# {"label": "Energieklasse", "value": "A"}
_ENERGY_KENMERK_RE = re.compile(
    r'"label"\s*:\s*"(?:Energieklasse|Energy class)"\s*,\s*"value"\s*:\s*"([A-G][+]*)"',
    re.IGNORECASE,
)


def _extract_energy_label(html: str) -> str | None:
    clean = _unescape_json_in_js(html)
    for pattern in (_ENERGY_DIRECT_RE, _ENERGY_KENMERK_RE):
        m = pattern.search(clean)
        if m:
            label = m.group(1).strip().upper()
            if label and label[0] in "ABCDEFG":
                return label[:2]
    return None


def _extract_photo_url(html: str) -> str | None:
    # og:image is al unescaped (staat buiten de JSON-payload).
    og_m = re.search(
        r'<meta\s+property="og:image"\s+content="([^"]+)"', html,
    )
    if og_m:
        url = unescape(og_m.group(1)).strip()
        if url.startswith("http"):
            return url[:500]
    clean = _unescape_json_in_js(html)
    src_m = re.search(r'"image"\s*:\s*\{[^}]*?"src"\s*:\s*"([^"]+)"', clean)
    if src_m:
        url = src_m.group(1).strip()
        if url.startswith("http"):
            return url[:500]
    return None


# ── Public API ──────────────────────────────────────────────────────────

def parse_move_html(url: str, html: str) -> dict:
    price = _extract_price(html)
    street, city = _extract_address(html)
    facts = _extract_summary_facts(html)
    energy = _extract_energy_label(html)
    photo = _extract_photo_url(html)

    name_parts = [p for p in (street, city) if p]
    name = ", ".join(name_parts) if name_parts else None

    if not name and price is None:
        raise MoveParseError(
            "Kon geen adres of prijs uit deze Move.nl-pagina halen — vul handmatig in."
        )

    return {
        "name": name,
        "offer": price,
        "energy_label": energy,
        "notes": "\n".join(facts) if facts else None,
        "photo_url": photo,
    }


def fetch_move(url: str) -> dict:
    if not is_move_url(url):
        raise MoveParseError("Deze URL lijkt niet op een move.nl-link.")
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "nl,en;q=0.5",
            },
            timeout=_FETCH_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        log.warning("Move-fetch faalde: %s", exc)
        raise MoveParseError(
            "Kon Move.nl niet bereiken — probeer het later opnieuw."
        ) from exc

    if resp.status_code == 404:
        raise MoveParseError("Deze Move.nl-pagina bestaat niet meer (404).")
    if resp.status_code >= 400:
        raise MoveParseError(
            f"Move.nl gaf status {resp.status_code} — vul handmatig in."
        )

    return parse_move_html(url, resp.text)
