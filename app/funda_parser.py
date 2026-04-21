"""Parser voor Funda-koop-pagina's.

Doel: uit een Funda-URL + HTML de velden halen die een hypotheek-scenario-
formulier nodig heeft (naam, vraagprijs, energielabel, korte samenvatting).

De parser is bewust gelaagd:

* `parse_funda_html(url, html)` is een pure functie die werkt op een HTML-
  string — geschikt voor unit tests zonder netwerk.
* `fetch_funda(url)` voert de netwerk-request uit en delegeert parsing.

Funda varieert in markup (Nuxt-payload, JSON-LD, meta-tags), dus we proberen
meerdere bronnen en kiezen de eerste die iets zinnigs oplevert. Als alles
faalt raisen we `FundaParseError`, met een leesbare NL-boodschap die de
front-end rechtstreeks kan tonen.
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


class FundaParseError(Exception):
    """Niet-fatale parse-fout: formulier blijft bruikbaar, user vult handmatig."""


_FUNDA_HOSTS = {"www.funda.nl", "funda.nl"}
_USER_AGENT = (
    "Mozilla/5.0 (compatible; CheckYourPockets/1.0; "
    "+https://github.com/gjagils/checkthepockets)"
)
_FETCH_TIMEOUT = 10  # seconden


# ── URL helpers ──────────────────────────────────────────────────────────

def is_funda_url(url: str) -> bool:
    """True als `url` op funda.nl wijst. Whitespace wordt getrimd."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() in _FUNDA_HOSTS


def _extract_address_from_url(url: str) -> tuple[str | None, str | None]:
    """Haal (straat + huisnummer, plaats) uit een Funda URL-path.

    Werkt met zowel `/detail/koop/<city>/huis-<slug>/...` als `/koop/<city>/huis-<slug>/...`.
    De slug is een kebab-case versie van de straat + huisnummer, soms met
    toevoegingen als `appartement` of `huis` als prefix.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None, None

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None, None

    # Vind het 'koop'-segment — city staat daar direct achter.
    try:
        koop_idx = parts.index("koop")
    except ValueError:
        return None, None
    if koop_idx + 1 >= len(parts):
        return None, None

    city_slug = parts[koop_idx + 1]
    city = city_slug.replace("-", " ").title() if city_slug else None

    street = None
    if koop_idx + 2 < len(parts):
        detail_slug = parts[koop_idx + 2]
        # Strip prefixes zoals 'huis-', 'appartement-'.
        for prefix in ("huis-", "appartement-", "woonhuis-"):
            if detail_slug.startswith(prefix):
                detail_slug = detail_slug[len(prefix):]
                break
        # Funda prefixt de slug vaak met het listing-ID: `43011275-adenauerlaan-114`.
        # Als het eerste token louter uit cijfers bestaat, beschouw het als ID en skip.
        tokens = detail_slug.split("-")
        if tokens and tokens[0].isdigit() and len(tokens) > 1:
            tokens = tokens[1:]
        street = " ".join(tokens).strip()
        if street:
            street = _titlecase_street(street)

    return street or None, city


def _titlecase_street(slug: str) -> str:
    """Title-case, maar hou huisnummer-suffix onveranderd."""
    tokens = slug.split()
    out = []
    for t in tokens:
        if any(c.isdigit() for c in t):
            out.append(t)  # "26" of "26a" onveranderd laten
        else:
            out.append(t.capitalize())
    return " ".join(out)


# ── HTML/JSON helpers ────────────────────────────────────────────────────

_JSON_LD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _extract_jsonld_blocks(html: str) -> list[dict[str, Any]]:
    """Geef alle parseable JSON-LD blokken terug."""
    out: list[dict[str, Any]] = []
    for match in _JSON_LD_RE.finditer(html):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


def _extract_price(html: str, jsonld: list[dict[str, Any]]) -> int | None:
    """Zoek de vraagprijs in JSON-LD of meta-tags; retourneer als int (EUR)."""
    # 1. JSON-LD: offers.price / price
    for block in jsonld:
        offers = block.get("offers")
        if isinstance(offers, dict):
            price = offers.get("price") or offers.get("priceSpecification", {}).get("price")
            val = _coerce_int(price)
            if val:
                return val
        direct = block.get("price")
        val = _coerce_int(direct)
        if val:
            return val

    # 2. meta tag og:price:amount (soms ingezet)
    m = re.search(
        r'<meta[^>]+property="(?:og:price:amount|product:price:amount)"[^>]+content="([^"]+)"',
        html,
        re.IGNORECASE,
    )
    if m:
        val = _coerce_int(m.group(1))
        if val:
            return val

    # 3. JSON-fragmenten in Nuxt/Next-payload. Funda wisselt tussen sleutels
    #    `asking_price`, `askingPrice`, `salePrice`, `offeringPrice` en legt ze
    #    soms diep genest in `transferOfOwnership` of `pricing`. We proberen
    #    alle bekende varianten — eerste die een realistisch bedrag oplevert
    #    wint.
    candidate_keys = (
        "asking_price",
        "askingPrice",
        "salePrice",
        "sale_price",
        "offeringPrice",
        "offering_price",
        "koopprijs",
        "rentPrice",  # alleen voor symmetrie, niet relevant voor koop
    )
    for key in candidate_keys:
        for match in re.finditer(
            rf'"{key}"\s*:\s*("?[\d.,\s€]+"?)', html,
        ):
            val = _coerce_int(match.group(1))
            if val:
                return val

    # 4. Funda's nieuwere Next-markup neemt prijs op als `"price": <int>` onder
    #    `transferOfOwnership` of `pricing`. Zoek het containerblok en graaf
    #    de eerste price-integer daaruit.
    for container in ("transferOfOwnership", "pricing"):
        for match in re.finditer(
            rf'"{container}"\s*:\s*\{{([^{{}}]{{0,400}})\}}', html,
        ):
            inner = match.group(1)
            p = re.search(r'"(?:price|askingPrice|sellingPrice)"\s*:\s*(\d{5,9})', inner)
            if p:
                val = _coerce_int(p.group(1))
                if val:
                    return val

    return None


def _extract_photo_url(html: str, jsonld: list[dict[str, Any]]) -> str | None:
    """Eerste foto: og:image (primair), daarna JSON-LD image-array (fallback)."""
    m = re.search(
        r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
        html,
        re.IGNORECASE,
    )
    if m:
        url = unescape(m.group(1)).strip()
        if url.startswith(("http://", "https://")):
            return url

    for block in jsonld:
        image = block.get("image")
        if isinstance(image, list):
            for item in image:
                if isinstance(item, str) and item.startswith(("http://", "https://")):
                    return item
                if isinstance(item, dict):
                    u = item.get("url") or item.get("contentUrl")
                    if isinstance(u, str) and u.startswith(("http://", "https://")):
                        return u
        elif isinstance(image, str) and image.startswith(("http://", "https://")):
            return image
        elif isinstance(image, dict):
            u = image.get("url") or image.get("contentUrl")
            if isinstance(u, str) and u.startswith(("http://", "https://")):
                return u

    return None


def _coerce_int(raw) -> int | None:
    """Convert losse prijs-notatie ('€ 425.000', '425000', 425000) naar int."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    s = str(raw).strip().strip('"')
    # Haal alles weg behalve cijfers. Voor Nederlandse notatie geldt: punt =
    # duizendtal, komma = decimaal. We negeren decimalen — huisprijzen zijn
    # integer.
    digits = re.sub(r"[^\d]", "", s.split(",")[0])
    if not digits:
        return None
    try:
        val = int(digits)
    except ValueError:
        return None
    # Sanity: we willen geen willekeurige nummers uit een pagina oppakken.
    if val < 10_000 or val > 100_000_000:
        return None
    return val


def _extract_energy_label(html: str, jsonld: list[dict[str, Any]]) -> str | None:
    """Zoek een energielabel 'A'..'G' (incl. A+, A++, ... ). We normaliseren
    tot één letter voor het scenario-formulier."""
    for block in jsonld:
        label = block.get("energyLabel") or block.get("energy_label")
        if isinstance(label, str) and label:
            m = re.match(r"\s*([A-G])", label.strip().upper())
            if m:
                return m.group(1)
    m = re.search(
        r'"(?:energy_label|energielabel)"\s*:\s*"([A-G])[^"]*"',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).upper()
    return None


_META_RE = re.compile(r'<meta[^>]+(?:property|name)="([^"]+)"[^>]+content="([^"]*)"', re.IGNORECASE)


def _extract_meta(html: str) -> dict[str, str]:
    return {k.lower(): unescape(v) for k, v in _META_RE.findall(html)}


def _extract_summary_facts(html: str, jsonld: list[dict[str, Any]]) -> list[str]:
    """Verzamel korte feiten voor de Notities-samenvatting."""
    facts: list[str] = []

    # Uit JSON-LD: floor size (m²), year built, property type
    for block in jsonld:
        ptype = block.get("@type")
        if isinstance(ptype, str) and ptype in {"Residence", "Apartment", "House"}:
            facts.append(f"Woningtype: {ptype}")
        floor = block.get("floorSize")
        if isinstance(floor, dict):
            val = floor.get("value")
            unit = floor.get("unitCode") or floor.get("unitText") or "m²"
            if val:
                facts.append(f"Woonoppervlakte: {val} {unit}")
        year = block.get("yearBuilt") or block.get("dateCreated")
        if year:
            y = str(year)[:4]
            if y.isdigit():
                facts.append(f"Bouwjaar: {y}")

    # Fallback: regex in raw HTML voor bouwjaar + oppervlakte
    if not any("Bouwjaar" in f for f in facts):
        m = re.search(r'"year_built"\s*:\s*(\d{4})', html)
        if m:
            facts.append(f"Bouwjaar: {m.group(1)}")
    if not any("Woonopp" in f for f in facts):
        m = re.search(r'"living_area"\s*:\s*(\d{1,4})', html)
        if m:
            facts.append(f"Woonoppervlakte: {m.group(1)} m²")

    # Perceel
    m = re.search(r'"plot_area"\s*:\s*(\d{1,5})', html)
    if m:
        facts.append(f"Perceel: {m.group(1)} m²")

    return facts


# ── Public API ───────────────────────────────────────────────────────────

def parse_funda_html(url: str, html: str) -> dict:
    """Parseer Funda-HTML naar scenario-veld-dict. Raist FundaParseError als
    er niet minstens een naam én een bod afgeleid kan worden."""
    street, city = _extract_address_from_url(url)
    jsonld = _extract_jsonld_blocks(html)

    price = _extract_price(html, jsonld)
    energy_label = _extract_energy_label(html, jsonld)
    facts = _extract_summary_facts(html, jsonld)
    photo_url = _extract_photo_url(html, jsonld)

    name_parts = [p for p in (street, city) if p]
    name = ", ".join(name_parts) if name_parts else None

    if not name and price is None:
        raise FundaParseError(
            "Kon geen adres of prijs uit deze Funda-pagina halen — vul handmatig in."
        )

    result = {
        "name": name,
        "offer": price,
        "energy_label": energy_label,
        "notes": "\n".join(facts) if facts else None,
        "photo_url": photo_url,
    }
    return result


def fetch_funda(url: str) -> dict:
    """Haal een Funda-pagina op en parseer. Raist `FundaParseError` bij alles
    wat misgaat — message is NL en UI-geschikt."""
    if not is_funda_url(url):
        raise FundaParseError("Deze URL lijkt niet op een funda.nl-link.")

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "nl,en;q=0.5"},
            timeout=_FETCH_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        log.warning("Funda-fetch faalde: %s", exc)
        raise FundaParseError("Kon Funda niet bereiken — probeer het later opnieuw.") from exc

    if resp.status_code == 404:
        raise FundaParseError("Deze Funda-pagina bestaat niet meer (404).")
    if resp.status_code >= 400:
        raise FundaParseError(f"Funda gaf status {resp.status_code} — vul handmatig in.")

    return parse_funda_html(url, resp.text)
