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


# ──────────────────────────────────────────────────────────────────────────────
# Recurring transaction pattern detection
# ──────────────────────────────────────────────────────────────────────────────

def detect_recurring_patterns(transactions: list[dict]) -> list[dict]:
    """
    Detect recurring patterns from a list of transactions.

    Input: [{"counterparty": str, "description": str, "amount": Decimal, "date": date,
             "category_id": int|None, "category_name": str|None}, ...]

    Returns list of candidates:
    [{"counterparty": str, "avg_amount": float, "frequency": str,
      "avg_days": float, "count": int, "amount_std": float,
      "category_id": int|None, "category_name": str|None,
      "first_date": str, "last_date": str, "dates": [str, ...]}, ...]
    """
    from collections import defaultdict
    from statistics import mean, stdev

    # Group by counterparty (lowercased, stripped)
    groups = defaultdict(list)
    for tx in transactions:
        cp = (tx.get("counterparty") or tx.get("description") or "").strip()
        if not cp:
            continue
        key = cp.lower()
        groups[key].append(tx)

    candidates = []

    for key, txs in groups.items():
        if len(txs) < 3:
            continue

        # Sort by date
        txs.sort(key=lambda t: t["date"])

        # Calculate intervals between consecutive transactions
        dates = [t["date"] for t in txs]
        amounts = [abs(float(t["amount"])) for t in txs]

        intervals = []
        for i in range(1, len(dates)):
            delta = (dates[i] - dates[i - 1]).days
            if delta > 0:
                intervals.append(delta)

        if not intervals:
            continue

        avg_days = mean(intervals)
        avg_amount = mean(amounts)
        amount_variation = stdev(amounts) if len(amounts) > 1 else 0.0

        # Skip if amount varies too wildly (> 50% of avg)
        if avg_amount > 0 and amount_variation / avg_amount > 0.5:
            continue

        # Determine frequency
        if 4 <= avg_days <= 10:
            frequency = "weekly"
        elif 25 <= avg_days <= 38:
            frequency = "monthly"
        elif 80 <= avg_days <= 110:
            frequency = "quarterly"
        elif 340 <= avg_days <= 400:
            frequency = "yearly"
        else:
            continue  # irregular, skip

        # Use the most common sign (positive = income, negative = expense)
        raw_amounts = [float(t["amount"]) for t in txs]
        neg_count = sum(1 for a in raw_amounts if a < 0)
        typical_amount = -avg_amount if neg_count > len(raw_amounts) / 2 else avg_amount

        # Most common category
        cat_counts = defaultdict(int)
        cat_names = {}
        for t in txs:
            cid = t.get("category_id")
            if cid:
                cat_counts[cid] += 1
                cat_names[cid] = t.get("category_name", "")
        top_cat_id = max(cat_counts, key=cat_counts.get) if cat_counts else None

        candidates.append({
            "counterparty": txs[0].get("counterparty") or txs[0].get("description") or key,
            "avg_amount": round(typical_amount, 2),
            "frequency": frequency,
            "avg_days": round(avg_days, 1),
            "count": len(txs),
            "amount_std": round(amount_variation, 2),
            "category_id": top_cat_id,
            "category_name": cat_names.get(top_cat_id, ""),
            "first_date": dates[0].isoformat(),
            "last_date": dates[-1].isoformat(),
        })

    # Sort by count (most frequent first)
    candidates.sort(key=lambda c: c["count"], reverse=True)
    return candidates


def enrich_recurring_with_ai(
    candidates: list[dict],
    categories: list[dict],
    existing_recurring: list[str],
) -> list[dict] | None:
    """
    Use Claude to enrich and filter recurring candidates.

    Args:
        candidates: Output from detect_recurring_patterns()
        categories: [{"id": int, "name": str}, ...]
        existing_recurring: List of existing recurring item names (to avoid duplicates)

    Returns enriched list with clean names and AI reasoning, or None on failure.
    """
    if not ANTHROPIC_API_KEY or not candidates:
        return None

    cat_list = ", ".join(c["name"] for c in categories) or "(geen)"
    existing_list = ", ".join(existing_recurring) or "(geen)"

    # Limit to top 15 candidates to keep the prompt manageable
    top = candidates[:15]
    candidates_text = "\n".join(
        f"- {c['counterparty']} | {c['count']}x | gem. €{c['avg_amount']} | "
        f"elke ~{c['avg_days']} dagen ({c['frequency']}) | "
        f"categorie: {c['category_name'] or 'geen'}"
        for c in top
    )

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Analyseer deze kandidaat-terugkerende transacties uit een persoonlijke "
                        "financiele app. Filter op echte terugkerende betalingen (abonnementen, "
                        "vaste lasten, salaris, etc.) en verwijder eenmalige patronen.\n\n"
                        f"Kandidaten:\n{candidates_text}\n\n"
                        f"Al bestaande terugkerende items: {existing_list}\n"
                        f"Beschikbare categorieen: {cat_list}\n\n"
                        "Antwoord UITSLUITEND als JSON array (geen markdown).\n"
                        "Filter kandidaten die al bestaan als terugkerend item.\n"
                        "Per item:\n"
                        "[\n"
                        "  {\n"
                        '    "counterparty_original": "originele naam",\n'
                        '    "name": "schone naam voor weergave",\n'
                        '    "frequency": "weekly|monthly|quarterly|yearly",\n'
                        '    "amount": bedrag als nummer (negatief = uitgave),\n'
                        '    "category_name": "best passende categorie of null",\n'
                        '    "counterparty_match": "zoekterm voor auto-matching",\n'
                        '    "is_recurring": true of false,\n'
                        '    "reasoning": "korte uitleg in het Nederlands"\n'
                        "  }\n"
                        "]\n"
                        "Geef alleen items terug waar is_recurring=true."
                    ),
                }
            ],
        )

        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        results = json.loads(text)

        # Resolve category names to IDs
        for item in results:
            item["category_id"] = None
            if item.get("category_name"):
                for cat in categories:
                    if cat["name"].lower() == item["category_name"].lower():
                        item["category_id"] = cat["id"]
                        break

        return [r for r in results if r.get("is_recurring")]

    except Exception as exc:
        logger.error("AI recurring analysis failed: %s", exc)
        return None
