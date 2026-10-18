"""Eén standaard categorieënset invoeren en de bestaande categorieën daarop afbeelden (ACT-56).

``plan_standard`` berekent alleen (preview); ``apply_standard`` voert uit zonder commit. De mapping werkt op
categorienaam (hoofdletterongevoelig), dus categorieën met dezelfde naam op meerdere rekeningen gaan samen
naar hetzelfde doel. Eén categorie ("Gerd-Jan/Nelleke") wordt gesplitst op tegenpartij, rekening en teken.
Wat niet in de mapping staat blijft ongemoeid en verschijnt in de preview onder "Blijft staan".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.account_merge import fold_category
from app.models import Category, Transaction

# (hoofdcategorie, [subcategorieën]); namen van subcategorieën zijn globaal uniek (unieke index op gedeelde namen).
STANDARD_SET: list[tuple[str, list[str]]] = [
    ("Inkomen", ["Bijdrage Gerd-Jan", "Bijdrage Nelleke", "Toeslagen en teruggaaf", "Kinderbijslag",
                 "Vakantiegeld en 13e maand", "Rente", "Giften ontvangen", "Overig inkomen"]),
    ("Wonen", ["Hypotheek", "Energie, water en belastingen", "Internet, tv en telefoon", "Schoonmaak",
               "Onderhoud en inrichting"]),
    ("Dagelijks", ["Boodschappen", "Lunch en onderweg", "Uit eten", "Huisdieren", "Kleding", "Verzorging",
                   "Overige uitgaven"]),
    ("Vervoer", ["Vervoerskosten"]),
    ("Zorg en verzekeringen", ["Verzekeringen", "Zorgkosten"]),
    ("Kinderen", ["Hannah", "Suze", "Sport en hobby", "Algemeen"]),
    ("Vrije tijd", ["Overig vrije tijd", "Sport", "Entertainment", "Abonnementen", "Vakantie", "Giften"]),
    ("Financieel", ["Bankkosten", "Goudkosten", "Bijdrage aan gezamenlijk"]),
    ("Sparen", ["Storting Nelleke", "Storting Gerd-Jan", "Storting samen", "Storting familie",
                "Storting zorgpremie", "Overige storting", "Terugboeking naar betaalrekening", "Opname spaardoel"]),
    ("Overboekingen", ["Eigen rekeningen"]),
]
INCOME_PARENTS = {"Inkomen"}
EXCLUDED_PARENTS = {"Overboekingen"}      # niet in budget en totalen
PALETTE = ["#89b4fa", "#f9a825", "#66bb6a", "#ef5350", "#ab47bc", "#26a69a", "#ff7043", "#8d6e63", "#78909c", "#ec407a"]

# Bronnaam (kleine letters) -> doel (hoofd, sub)
MAPPING: dict[str, tuple[str, str]] = {
    "restinkomen": ("Inkomen", "Overig inkomen"), "teruggaaf": ("Inkomen", "Toeslagen en teruggaaf"),
    "belasting teruggave": ("Inkomen", "Toeslagen en teruggaaf"),
    "teruggaves (verzekering/energie)": ("Inkomen", "Toeslagen en teruggaaf"),
    "kinderbijslag": ("Inkomen", "Kinderbijslag"),
    "nelleke vakantietoeslag": ("Inkomen", "Vakantiegeld en 13e maand"),
    "vakantiegeld gj": ("Inkomen", "Vakantiegeld en 13e maand"), "13e maand gj": ("Inkomen", "Vakantiegeld en 13e maand"),
    "rente": ("Inkomen", "Rente"), "rente gj": ("Inkomen", "Rente"),
    "overboek": ("Overboekingen", "Eigen rekeningen"),
    "bankkosten": ("Financieel", "Bankkosten"), "goudkosten": ("Financieel", "Goudkosten"),
    "boodschappen": ("Dagelijks", "Boodschappen"), "huisdieren": ("Dagelijks", "Huisdieren"),
    "uit eten": ("Dagelijks", "Uit eten"), "overige uitgaven": ("Dagelijks", "Overige uitgaven"),
    "kleding": ("Dagelijks", "Kleding"),
    "goede doelen": ("Vrije tijd", "Giften"), "vrije tijd": ("Vrije tijd", "Overig vrije tijd"),
    "entertainment": ("Vrije tijd", "Entertainment"), "abonnementen": ("Vrije tijd", "Abonnementen"),
    "schoonmaak": ("Wonen", "Schoonmaak"), "hypotheek": ("Wonen", "Hypotheek"),
    "energie/water/belastingen": ("Wonen", "Energie, water en belastingen"),
    "transport": ("Vervoer", "Vervoerskosten"),
    "verzekeringen": ("Zorg en verzekeringen", "Verzekeringen"), "zorgkosten": ("Zorg en verzekeringen", "Zorgkosten"),
    "hannah": ("Kinderen", "Hannah"), "suze": ("Kinderen", "Suze"),
    "kidssport": ("Kinderen", "Sport en hobby"), "kids-algemeen": ("Kinderen", "Algemeen"),
    "sparen": ("Sparen", "Storting samen"), "maandelijks sparen": ("Sparen", "Storting samen"),
    "ziektekosten": ("Sparen", "Storting zorgpremie"),
    "nelleke bijdrage": ("Sparen", "Storting Nelleke"), "nelleke hannah sparen": ("Sparen", "Storting Nelleke"),
    "gerd-jan bijdrage": ("Sparen", "Storting Gerd-Jan"), "gerd-jan maandelijks": ("Sparen", "Storting Gerd-Jan"),
    "extra storting gj": ("Sparen", "Storting Gerd-Jan"),
    "oma johanna": ("Sparen", "Storting familie"), "opa/oma steendam": ("Sparen", "Storting familie"),
    "extra storting": ("Sparen", "Overige storting"),
    "bunq teruboek": ("Sparen", "Terugboeking naar betaalrekening"),
    "terugboek samen": ("Sparen", "Terugboeking naar betaalrekening"),
    "bunq spaar": ("Sparen", "Terugboeking naar betaalrekening"),
    "huiskosten": ("Sparen", "Opname spaardoel"), "huis aflossen": ("Sparen", "Opname spaardoel"),
    "vakantie": ("Sparen", "Opname spaardoel"), "uitgave": ("Sparen", "Opname spaardoel"),
}

# Bronnaam die per transactie wordt verdeeld. Eerste regel die past wint; ``default`` voor de rest.
# Velden: account (exact, kleine letters), counterparty/description (regex), sign ("+" of "-").
SPLITS: dict[str, dict] = {
    "gerd-jan/nelleke": {
        "rules": [
            {"counterparty": r"GJA VAN GILS", "target": ("Inkomen", "Bijdrage Gerd-Jan")},
            {"counterparty": r"N STEENDAM CJ", "account": "samen betaal", "sign": "-", "target": ("Sparen", "Storting samen")},
            {"counterparty": r"N STEENDAM", "account": "samen betaal", "sign": "+", "target": ("Inkomen", "Bijdrage Nelleke")},
            {"counterparty": r"N STEENDAM CJ", "account": "samen spaar bunq", "target": ("Sparen", "Storting Nelleke")},
            {"account": "abn samen spaar", "sign": "+", "target": ("Sparen", "Storting samen")},
        ],
        "default": ("Inkomen", "Overig inkomen"),
    },
}

Target = tuple[str, str]


@dataclass
class SourceRow:
    category: Category
    account_name: str
    transactions: int
    target: Target | None                 # None = blijft staan
    split: dict[Target, int] = field(default_factory=dict)
    changed: bool = False                 # gebruiker koos een ander doel


@dataclass
class StandardPlan:
    to_create: list[Target | tuple[str, None]] = field(default_factory=list)
    rows: list[SourceRow] = field(default_factory=list)
    archive_parents: list[Category] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)       # alle keuzes voor de preview

    @property
    def moves(self) -> list[SourceRow]:
        return [r for r in self.rows if r.target or r.split]

    @property
    def untouched(self) -> list[SourceRow]:
        return [r for r in self.rows if not (r.target or r.split)]


def all_targets() -> list[Target]:
    return [(h, s) for h, subs in STANDARD_SET for s in subs]


def target_key(target: Target) -> str:
    return f"{target[0]}|{target[1]}"


def parse_target(key: str) -> Target | None:
    parts = key.split("|", 1)
    return (parts[0], parts[1]) if len(parts) == 2 and (parts[0], parts[1]) in set(all_targets()) else None


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


def _matches(rule: dict, tx: Transaction, account_name: str) -> bool:
    if "account" in rule and _norm(account_name) != rule["account"]:
        return False
    if "counterparty" in rule and not re.search(rule["counterparty"], tx.counterparty or "", re.IGNORECASE):
        return False
    if "description" in rule and not re.search(rule["description"], tx.description or "", re.IGNORECASE):
        return False
    if rule.get("sign") == "+" and not tx.amount > 0:
        return False
    if rule.get("sign") == "-" and not tx.amount < 0:
        return False
    return True


def split_target(spec: dict, tx: Transaction, account_name: str) -> Target:
    for rule in spec["rules"]:
        if _matches(rule, tx, account_name):
            return rule["target"]
    return spec["default"]


def plan_standard(db: Session, user_id: int, overrides: dict[int, str] | None = None) -> StandardPlan:
    """``overrides``: {categorie-id: "Hoofd|Sub" of "" (laten staan)} uit de preview."""
    overrides = overrides or {}
    cats = db.query(Category).filter(Category.user_id == user_id, Category.is_archived == 0).all()
    by_id = {c.id: c for c in cats}
    counts = dict(
        db.query(Transaction.category_id, func.count(Transaction.id))
        .filter(Transaction.category_id.isnot(None)).group_by(Transaction.category_id).all()
    )
    plan = StandardPlan(targets=all_targets())
    shared_parents = {c.name for c in cats if c.account_id is None and c.parent_id is None}
    shared_children = {(by_id[c.parent_id].name, c.name): c for c in cats
                       if c.account_id is None and c.parent_id in by_id}

    used: set[Target] = set()
    standard_paths = set(all_targets())

    def is_standard(c: Category) -> bool:
        """Een gedeelde categorie die al op zijn plek in de standaardset staat is nooit een bron."""
        return c.account_id is None and c.parent_id in by_id and (by_id[c.parent_id].name, c.name) in standard_paths

    candidates = [c for c in cats if not is_standard(c) and (c.parent_id is not None
                  or (c.account_id is not None and counts.get(c.id, 0) > 0))]       # hoofdcategorie met eigen boekingen
    for category in sorted(candidates, key=lambda c: c.id):
        key = _norm(category.name)
        default = MAPPING.get(key)
        row = SourceRow(category, category.account.name if category.account else "—",
                        counts.get(category.id, 0), default)
        spec = SPLITS.get(key)
        if category.id in overrides:
            chosen = parse_target(overrides[category.id]) if overrides[category.id] else None
            row.target, row.changed, spec = chosen, chosen != default, None
        if spec:
            row.target = None
            for tx in db.query(Transaction).filter(Transaction.category_id == category.id).all():
                dest = split_target(spec, tx, tx.account.name)
                row.split[dest] = row.split.get(dest, 0) + 1
            if not row.split:                       # niets te verdelen: de lege categorie gaat naar de standaard
                row.target = spec["default"]
            used.update(row.split)
        if row.target is not None:
            parent_name = by_id[category.parent_id].name if category.parent_id else None
            if category.account_id is None and (parent_name, category.name) == row.target:
                row.target = None                   # staat al op de goede plek
            else:
                used.add(row.target)
        plan.rows.append(row)

    for hoofd, sub in all_targets():          # ook ongebruikte categorieën: de hele standaardset hoort beschikbaar te zijn
        if (hoofd, sub) not in shared_children:
            if hoofd not in shared_parents and (hoofd, None) not in plan.to_create:
                plan.to_create.append((hoofd, None))
            plan.to_create.append((hoofd, sub))

    moved_ids = {r.category.id for r in plan.moves}
    for category in cats:
        if category.parent_id is not None or category.account_id is None:
            continue
        kids = [c for c in cats if c.parent_id == category.id]
        direct = counts.get(category.id, 0)
        if direct == 0 and all(k.id in moved_ids for k in kids):
            plan.archive_parents.append(category)
    return plan


def _ensure_target(db: Session, user_id: int, hoofd: str, sub: str | None,
                   cache: dict[tuple, Category]) -> Category:
    key = (hoofd, sub)
    if key in cache:
        return cache[key]
    parent = cache.get((hoofd, None))
    if parent is None:
        parent = (db.query(Category).filter(Category.user_id == user_id, Category.account_id.is_(None),
                                            Category.parent_id.is_(None), Category.name == hoofd,
                                            Category.is_archived == 0).first())
        if parent is None:
            index = [h for h, _ in STANDARD_SET].index(hoofd)
            parent = Category(user_id=user_id, account_id=None, name=hoofd, parent_id=None,
                              color=PALETTE[index % len(PALETTE)], is_income=1 if hoofd in INCOME_PARENTS else 0,
                              exclude_from_budget=1 if hoofd in EXCLUDED_PARENTS else 0,
                              exclude_from_totals=1 if hoofd in EXCLUDED_PARENTS else 0, sort_order=index)
            db.add(parent)
            db.flush()
        cache[(hoofd, None)] = parent
    if sub is None:
        return parent
    child = (db.query(Category).filter(Category.user_id == user_id, Category.account_id.is_(None),
                                       Category.parent_id == parent.id, Category.name == sub,
                                       Category.is_archived == 0).first())
    if child is None:
        order = [s for h, subs in STANDARD_SET if h == hoofd for s in subs].index(sub)
        child = Category(user_id=user_id, account_id=None, name=sub, parent_id=parent.id, color=parent.color,
                         is_income=parent.is_income, exclude_from_budget=parent.exclude_from_budget,
                         exclude_from_totals=parent.exclude_from_totals, sort_order=order)
        db.add(child)
        db.flush()
    cache[key] = child
    return child


def apply_standard(db: Session, user_id: int, overrides: dict[int, str] | None = None) -> StandardPlan:
    """Voert het plan uit; de aanroeper commit. Plant opnieuw op actuele data."""
    plan = plan_standard(db, user_id, overrides)
    cache: dict[tuple, Category] = {}
    for row in plan.moves:
        category = row.category
        if row.split:
            spec = SPLITS[_norm(category.name)]
            for tx in db.query(Transaction).filter(Transaction.category_id == category.id).all():
                dest = split_target(spec, tx, tx.account.name)
                tx.category_id = _ensure_target(db, user_id, dest[0], dest[1], cache).id
            db.flush()
            # alles is verdeeld: de lege bron mag weg
            fold_category(db, category.id, _ensure_target(db, user_id, *spec["default"], cache).id, sum_budgets=True)
        elif row.target:
            target = _ensure_target(db, user_id, row.target[0], row.target[1], cache)
            if target.id != category.id:
                fold_category(db, category.id, target.id, sum_budgets=True)
        db.flush()
    for hoofd, sub in plan.to_create:
        _ensure_target(db, user_id, hoofd, sub, cache)
    for parent in plan.archive_parents:
        remaining = db.query(Category).filter(Category.parent_id == parent.id).count()
        if remaining == 0 and db.get(Category, parent.id) is not None:
            parent.is_archived = 1
    return plan
