"""Categoriesuggesties voor ongecategoriseerde transacties (ACT-58).

Twee lagen, van gratis naar duur:

1. **Historie** (geen AI): dezelfde IBAN, tegenpartij of merchant uit de omschrijving die je eerder
   een categorie gaf. Een sleutel telt alleen met een duidelijke meerderheid; anders proberen we de
   volgende (een betaaldienst-IBAN die bij tien winkels hoort, wint dus niet van de winkelnaam).
2. **AI** voor wat overblijft: unieke tegenpartijen zonder historie gaan in één batch-call naar
   Claude, en het antwoord wordt per tegenpartij bewaard in `MerchantCategorySuggestion`. Elke naam
   kost zo hooguit één keer een call. Dit draait na een import of sync, of op de knop, nooit bij het
   laden van een pagina.

`counterparty`, `counterparty_iban` en `description` zijn versleuteld met een willekeurige IV, dus
alles wordt in Python geteld (zie ook `rules_engine.suggest_rules`).
"""
import hashlib
import hmac
import logging
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import ai_client
from app.ai_suggest import ai_available, parse_description
from app.config import SECRET_KEY
from app.models import Account, Category, MerchantCategorySuggestion, Transaction

logger = logging.getLogger(__name__)

# Aandeel van de meest gekozen categorie voordat een sleutel als suggestie telt.
MIN_SHARE = 0.6
# Maximaal aantal tegenpartijen per AI-call; de rest volgt bij de volgende import of klik.
AI_BATCH_SIZE = 40

_LEGAL_FORMS = {"bv", "nv", "vof", "cv", "holding", "bank", "nl", "nederland", "the", "de", "het"}


def normalize_name(value: str | None) -> str:
    """Maak een naam vergelijkbaar: kleine letters, geen leestekens, rechtsvormen of winkelnummers."""
    if not value:
        return ""
    value = re.sub(r"\b([a-z])\.(?=[a-z]\.?\b)", r"\1", value.lower())  # b.v. -> bv
    tokens = re.split(r"[^0-9a-zà-ÿ]+", value)
    kept = [t for t in tokens if t and not t.isdigit() and t not in _LEGAL_FORMS]
    return " ".join(kept)[:80]


def normalize_iban(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def merchant_name(tx: Transaction) -> str:
    """De beste naam voor een tegenpartij: het veld zelf, anders de merchant uit de omschrijving."""
    return normalize_name(tx.counterparty) or normalize_name(parse_description(tx.description or "")["merchant"])


def _keys(tx: Transaction) -> list[tuple[str, str]]:
    """Herkenningssleutels in volgorde van betrouwbaarheid."""
    keys = []
    iban = normalize_iban(tx.counterparty_iban)
    if iban:
        keys.append(("iban", iban))
    cp = normalize_name(tx.counterparty)
    if cp:
        keys.append(("counterparty", cp))
    parsed = normalize_name(parse_description(tx.description or "")["merchant"])
    if parsed and parsed != cp:
        keys.append(("merchant", parsed))
    return keys


def merchant_hash(name: str) -> str:
    """HMAC van een genormaliseerde naam: opzoekbaar zonder leesbare tegenpartij in de database."""
    return hmac.new(SECRET_KEY.encode(), name.encode(), hashlib.sha256).hexdigest()


@dataclass
class Suggestion:
    category_id: int
    category_name: str
    source: str        # "historie" | "ai"
    count: int = 0     # bij historie: zo vaak gekozen
    total: int = 0     # bij historie: zo vaak gecategoriseerd met deze sleutel

    @property
    def label(self) -> str:
        if self.source == "ai":
            return "AI-suggestie"
        if self.count == self.total:
            return f"{self.count}× eerder"
        return f"{self.count} van {self.total}× eerder"


class _Categories:
    """Kiesbare categorieën: subcategorieën, niet gearchiveerd, gedeeld of van de eigen rekening."""

    def __init__(self, db: Session, user_id: int):
        self.by_id = {
            c.id: c for c in db.query(Category).filter(
                Category.user_id == user_id, Category.parent_id.isnot(None), Category.is_archived == 0,
            )
        }

    def allowed(self, category_id: int | None, account_id: int) -> bool:
        cat = self.by_id.get(category_id)
        return cat is not None and cat.account_id in (None, account_id)


def _history_index(db: Session, user_id: int) -> dict[tuple[str, str], Counter]:
    rows = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.category_id.isnot(None),
            Transaction.is_projected == 0,
            Transaction.parent_id.is_(None),  # splitsdelen zeggen niets over de tegenpartij als geheel
        )
        .all()
    )
    index: dict[tuple[str, str], Counter] = {}
    for tx in rows:
        for key in _keys(tx):
            index.setdefault(key, Counter())[tx.category_id] += 1
    return index


def _from_history(tx: Transaction, index, cats: _Categories) -> Suggestion | None:
    for key in _keys(tx):
        counts = index.get(key)
        if not counts:
            continue
        valid = {cid: n for cid, n in counts.items() if cats.allowed(cid, tx.account_id)}
        if not valid:
            continue
        total = sum(valid.values())
        best, n = max(valid.items(), key=lambda kv: kv[1])
        if n / total >= MIN_SHARE:
            return Suggestion(best, cats.by_id[best].name, "historie", n, total)
    return None


def _ai_cache(db: Session, user_id: int) -> dict[str, int | None]:
    return {
        row.merchant_hash: row.category_id
        for row in db.query(MerchantCategorySuggestion).filter(MerchantCategorySuggestion.user_id == user_id)
    }


@dataclass
class SuggestionResult:
    by_tx: dict[int, Suggestion]
    ai_pending: int    # tegenpartijen zonder historie en zonder AI-antwoord


def suggest_for(db: Session, user_id: int, transactions: list[Transaction]) -> SuggestionResult:
    """Suggesties voor de ongecategoriseerde transacties in `transactions` (historie, dan AI-cache)."""
    open_txs = [t for t in transactions if t.category_id is None and not t.is_projected and not t.is_excluded]
    if not open_txs:
        return SuggestionResult({}, 0)
    cats = _Categories(db, user_id)
    index = _history_index(db, user_id)
    cache = _ai_cache(db, user_id)
    by_tx: dict[int, Suggestion] = {}
    pending: set[str] = set()
    for tx in open_txs:
        found = _from_history(tx, index, cats)
        if found is None:
            name = merchant_name(tx)
            if name:
                h = merchant_hash(name)
                if h not in cache:
                    pending.add(h)
                elif cats.allowed(cache[h], tx.account_id):
                    found = Suggestion(cache[h], cats.by_id[cache[h]].name, "ai")
        if found:
            by_tx[tx.id] = found
    return SuggestionResult(by_tx, len(pending))


def _ai_candidates(db: Session, user_id: int) -> dict[str, dict]:
    """Unieke tegenpartijen van open transacties zonder historie en zonder eerder AI-antwoord."""
    open_txs = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.category_id.is_(None),
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
        )
        .order_by(Transaction.date.desc())
        .all()
    )
    if not open_txs:
        return {}
    cats = _Categories(db, user_id)
    index = _history_index(db, user_id)
    cache = _ai_cache(db, user_id)
    groups: dict[str, dict] = {}
    for tx in open_txs:
        if _from_history(tx, index, cats):
            continue
        name = merchant_name(tx)
        if not name:
            continue
        h = merchant_hash(name)
        if h in cache:
            continue
        group = groups.setdefault(h, {"name": name, "description": tx.description or "", "count": 0, "amounts": []})
        group["count"] += 1
        if len(group["amounts"]) < 3:
            group["amounts"].append(f"{tx.amount:.2f}")
    return groups


def fill_ai_suggestions(db: Session, user_id: int) -> int:
    """Vraag in één call een categorie voor tegenpartijen zonder historie; geeft het aantal antwoorden.

    Faalt stil (log) zonder API-sleutel of bij een API-fout: de historie-suggesties werken door.
    """
    if not ai_available():
        return 0
    groups = _ai_candidates(db, user_id)
    if not groups:
        return 0
    # Meeste transacties eerst: daar bespaart een suggestie het meeste werk.
    batch = sorted(groups.items(), key=lambda kv: -kv[1]["count"])[:AI_BATCH_SIZE]
    cats = _Categories(db, user_id)
    if not cats.by_id:
        return 0
    cat_list = "\n".join(
        f"  id={c.id}: \"{c.name}\" (onder \"{c.parent.name}\")"
        for c in sorted(cats.by_id.values(), key=lambda c: (c.parent.name, c.name))
    )
    items = "\n".join(
        f"{i}. {g['name']} | voorbeeld: \"{g['description'][:120]}\" | bedragen: {', '.join(g['amounts'])}"
        for i, (_, g) in enumerate(batch, 1)
    )
    try:
        answer = ai_client.call_json(
            (
                "Kies voor elke tegenpartij uit een Nederlandse bankrekening de best passende "
                "subcategorie. Negatieve bedragen zijn uitgaven, positieve inkomsten.\n\n"
                f"Tegenpartijen:\n{items}\n\n"
                f"Subcategorieën (kies ALLEEN uit deze ids):\n{cat_list}\n\n"
                "Antwoord UITSLUITEND als JSON-array, één item per tegenpartij, in dezelfde volgorde:\n"
                '[{"nr": 1, "category_id": 12}, {"nr": 2, "category_id": null}]\n'
                "Gebruik null als je het niet redelijk zeker weet."
            ),
            max_tokens=60 + 25 * len(batch),
        )
    except Exception as exc:
        logger.error("AI-categoriesuggesties mislukt: %s", exc)
        return 0

    chosen: dict[int, int | None] = {}
    for item in answer if isinstance(answer, list) else []:
        nr, cid = item.get("nr"), item.get("category_id")
        if isinstance(nr, int) and 1 <= nr <= len(batch):
            chosen[nr] = cid if isinstance(cid, int) and cid in cats.by_id else None
    # Alleen tegenpartijen waarop de AI antwoordde bewaren; een ontbrekend item wordt later opnieuw gevraagd.
    for nr, cid in chosen.items():
        db.add(MerchantCategorySuggestion(user_id=user_id, merchant_hash=batch[nr - 1][0], category_id=cid))
    db.commit()
    logger.info("AI-categoriesuggesties: %d tegenpartijen beantwoord voor user %s", len(chosen), user_id)
    return len(chosen)


def fill_ai_suggestions_in_background(user_id: int) -> None:
    """Voor FastAPI BackgroundTasks: eigen sessie, want die van het verzoek is dan al dicht."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        fill_ai_suggestions(db, user_id)
    except Exception:
        db.rollback()
        logger.exception("AI-categoriesuggesties op de achtergrond mislukt voor user %s", user_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Per tegenpartij categoriseren (ACT-60)
# ---------------------------------------------------------------------------

# Kortere regeltekst matcht te makkelijk op andere namen ("bol" in "symbol").
RULE_MIN_LENGTH = 4


@dataclass
class CounterpartyGroup:
    key: str                          # merchant_hash van de genormaliseerde naam
    name: str                         # meest voorkomende leesbare naam
    transactions: list[Transaction]
    suggestion: Suggestion | None = None
    rule_field: str | None = None     # "counterparty" | "description", of None als geen veilige regel
    rule_value: str | None = None

    @property
    def count(self) -> int:
        return len(self.transactions)

    @property
    def total(self):
        return sum(t.amount for t in self.transactions)

    @property
    def account_ids(self) -> set[int]:
        return {t.account_id for t in self.transactions}


def _display_name(tx: Transaction) -> str:
    return (tx.counterparty or "").strip() or (parse_description(tx.description or "")["merchant"] or "").strip()


def _rule_for(name: str, transactions: list[Transaction]) -> tuple[str | None, str | None]:
    """Een 'bevat'-regel die alle transacties van de groep raakt, of (None, None).

    Eerst de genormaliseerde naam (vangt winkelnummers en rechtsvormen), anders de meest voorkomende
    letterlijke tegenpartij. Normaliseren haalt leestekens weg ("h&m" → "h m"), dus we controleren
    of de tekst echt in elke transactie staat.
    """
    if all((t.counterparty or "").strip() for t in transactions):
        field, values = "counterparty", [t.counterparty.lower() for t in transactions]
        raw = Counter(t.counterparty.strip() for t in transactions).most_common(1)[0][0]
        candidates = [name, raw]
    elif not any((t.counterparty or "").strip() for t in transactions):
        field, values = "description", [(t.description or "").lower() for t in transactions]
        candidates = [name]
    else:
        return None, None
    for value in candidates:
        if len(value) >= RULE_MIN_LENGTH and all(value.lower() in v for v in values):
            return field, value
    return None, None


def open_groups(
    db: Session, user_id: int, *, account_id: int | None = None, date_from=None, date_to=None,
    with_suggestions: bool = True,
) -> tuple[list[CounterpartyGroup], int]:
    """Ongecategoriseerde transacties per tegenpartij, grootste groep eerst.

    Geeft ook het aantal open transacties zonder herkenbare naam (die passen in geen groep).
    `with_suggestions=False` slaat de historie en AI-cache over: dat is het zware deel (alle
    gecategoriseerde transacties ontsleutelen) en toewijzen heeft het niet nodig.
    """
    split_parent_ids = (
        db.query(Transaction.parent_id).filter(Transaction.parent_id.isnot(None)).distinct().scalar_subquery()
    )
    query = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user_id,
            Transaction.category_id.is_(None),
            Transaction.is_excluded == 0,
            Transaction.is_projected == 0,
            Transaction.id.notin_(split_parent_ids),
        )
    )
    if account_id:
        query = query.filter(Transaction.account_id == account_id)
    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date <= date_to)
    open_txs = query.order_by(Transaction.date.desc(), Transaction.id.desc()).all()

    by_key: dict[str, list[Transaction]] = {}
    unnamed = 0
    for tx in open_txs:
        name = merchant_name(tx)
        if not name:
            unnamed += 1
            continue
        by_key.setdefault(merchant_hash(name), []).append(tx)

    suggestions = suggest_for(db, user_id, open_txs).by_tx if with_suggestions else {}
    groups = []
    for key, txs in by_key.items():
        name = merchant_name(txs[0])
        display = Counter(_display_name(t) for t in txs).most_common(1)[0][0] or name
        found = [suggestions[t.id] for t in txs if t.id in suggestions]
        suggestion = None
        if found:
            best = Counter(s.category_id for s in found).most_common(1)[0][0]
            suggestion = next(s for s in found if s.category_id == best)
        field, value = _rule_for(name, txs)
        groups.append(CounterpartyGroup(key, display, txs, suggestion, field, value))
    groups.sort(key=lambda g: (-g.count, g.name.lower()))
    return groups, unnamed


def allowed_categories(db: Session, user_id: int) -> _Categories:
    return _Categories(db, user_id)
