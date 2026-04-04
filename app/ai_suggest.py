"""
Smart rule suggestion: regex-based description parsing + Claude API category suggestion.
Sprint 17 — extracts merchant names from bank descriptions, suggests categories.

If ANTHROPIC_API_KEY is not set, only regex parsing is available (no AI suggestions).
"""

import json
import logging
import re

from app.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Regex parsers for known bank description formats
# ──────────────────────────────────────────────────────────────────────────────

def _parse_bea(desc: str) -> dict | None:
    """ABN AMRO BEA (PIN/betaalautomaat) transactions.
    Format: BEA, Apple Pay AH Vleuten NR:X70J2J, 01.04.26/10:43 VLEUTEN KAARTNUMMER: **3103
    """
    m = re.match(
        r'BEA[,\s]+(?:Apple Pay|Google Pay|Contactloos|Samsung Pay)?\s*(.+?)\s+NR:[A-Z0-9]+',
        desc, re.IGNORECASE,
    )
    if m:
        return {"merchant": m.group(1).strip(), "type": "pin"}
    return None


def _parse_gea(desc: str) -> dict | None:
    """ABN AMRO GEA (geldautomaat) transactions.
    Format: GEA, Geldmaat NR:12345, 01.04.26/10:43 UTRECHT
    """
    m = re.match(
        r'GEA[,\s]+(.+?)\s+NR:[A-Z0-9]+',
        desc, re.IGNORECASE,
    )
    if m:
        return {"merchant": m.group(1).strip(), "type": "atm"}
    return None


def _parse_sepa(desc: str) -> dict | None:
    """SEPA overschrijving / incasso — /NAME/... field."""
    m = re.search(r'/NAME/([^/]+)', desc)
    if m:
        return {"merchant": m.group(1).strip(), "type": "sepa"}
    return None


def _parse_ideal(desc: str) -> dict | None:
    """iDEAL payments."""
    m = re.match(r'iDEAL\s+(?:betaling\s+aan\s+)?(.+)', desc, re.IGNORECASE)
    if m:
        return {"merchant": m.group(1).strip(), "type": "ideal"}
    return None


def _parse_trtp(desc: str) -> dict | None:
    """TRTP-style SEPA descriptions (ING, Rabobank)."""
    m = re.search(r'/TRTP/[^/]*/.*?/NAME/([^/]+)', desc)
    if m:
        return {"merchant": m.group(1).strip(), "type": "sepa"}
    return None


def parse_description(description: str) -> dict:
    """
    Extract merchant info from a bank transaction description.
    Returns {"merchant": "...", "type": "pin|atm|sepa|ideal|unknown"}.
    """
    if not description:
        return {"merchant": "", "type": "unknown"}

    for parser in [_parse_bea, _parse_gea, _parse_sepa, _parse_trtp, _parse_ideal]:
        result = parser(description)
        if result:
            return result

    return {"merchant": description.strip()[:80], "type": "unknown"}


# ──────────────────────────────────────────────────────────────────────────────
# Claude API suggestion
# ──────────────────────────────────────────────────────────────────────────────

def suggest_rule(
    description: str,
    counterparty: str | None,
    categories: list[dict],
) -> dict | None:
    """
    Call Claude to suggest rule parameters from a transaction description.

    Args:
        description: Raw bank transaction description
        counterparty: Counterparty name (may be empty/None)
        categories: [{"id": int, "name": str}, ...]

    Returns dict with keys: match_value, match_field, counterparty_clean,
           category_id, category_name, reasoning — or None on failure.
    """
    if not ANTHROPIC_API_KEY:
        return None

    parsed = parse_description(description)
    merchant = parsed.get("merchant", "")

    cat_list = ", ".join(c["name"] for c in categories) or "(geen categorieën)"

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Analyseer deze Nederlandse banktransactie en stel een "
                        "categoriseerregel voor.\n\n"
                        f"Omschrijving: {description}\n"
                        f"Tegenpartij: {counterparty or 'onbekend'}\n"
                        f"Geëxtraheerde merchant (regex): {merchant}\n\n"
                        f"Beschikbare categorieën: {cat_list}\n\n"
                        "Antwoord UITSLUITEND als JSON (geen markdown):\n"
                        "{\n"
                        '  "match_value": "korte unieke zoekterm voor deze merchant",\n'
                        '  "match_field": "description" of "counterparty",\n'
                        '  "counterparty_clean": "schone volledige naam",\n'
                        '  "category_name": "best passende categorie uit de lijst, of null",\n'
                        '  "reasoning": "1 zin uitleg in het Nederlands"\n'
                        "}"
                    ),
                }
            ],
        )

        text = resp.content[0].text.strip()
        # Strip optional markdown fencing
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(text)

        # Resolve category name → id
        if result.get("category_name"):
            for cat in categories:
                if cat["name"].lower() == result["category_name"].lower():
                    result["category_id"] = cat["id"]
                    break
            else:
                result["category_id"] = None
        else:
            result["category_id"] = None

        return result

    except Exception as exc:
        logger.error("AI suggest failed: %s", exc)
        return None


def ai_available() -> bool:
    """True when the Anthropic API key is configured."""
    return bool(ANTHROPIC_API_KEY)
