"""Seed demo-user met vooringevulde data (LIN-46, fase 1).

Doel: bij live demo's geen lege schermen. De functie `seed_demo_user()` wordt
aangeroepen vanuit een admin-only endpoint (`POST /admin/demo/seed`) — zie
`app/routers/admin.py`. Directe CLI-aanroep is **niet** meer ondersteund om te
voorkomen dat iemand per ongeluk op productie seedt zonder admin-sessie.

Wat wordt aangemaakt (of ge-reset bij her-aanroep):

* Non-admin user (hypotheek-module blijft zo buiten de demo — zie GJA-47 voor
  de separate feature-flag werk).
* 2 personen (Demo Alex + Demo Sam).
* 3 rekeningen (betaal/spaar/gezamenlijk) met owners.
* 10 categorieën (incl. `cost_scale_type` markering waar relevant).
* 12 maanden transacties + 5 ongecategoriseerde voor de inbox-badge.
* 12 maanden budgetten per uitgaven-categorie.

**Niet** in scope: HouseholdFinance, MortgageScenario, rente-tabel,
portfolio, net worth snapshots, recurring. Die komen pas terug zodra de
demo-user hypotheek-toegang krijgt (GJA-47) of als onderdeel van Fase 2.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.database import SessionLocal
from app.models import (
    Account,
    Budget,
    Category,
    Person,
    Transaction,
    User,
)


DEFAULT_USERNAME = "demo"
DEFAULT_PASSWORD = "demodemo"
DEFAULT_EMAIL = "demo@checkthepockets.nl"


# ── Datamodel voor de seed-fixtures ────────────────────────────────────────


@dataclass(frozen=True)
class CategorySpec:
    name: str
    is_income: bool = False
    cost_scale_type: str | None = None
    monthly_budget: Decimal | None = None  # None = geen budget (income/overig)


@dataclass(frozen=True)
class TxTemplate:
    counterparty: str
    amount: Decimal
    category: str
    day: int


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec("Salaris", is_income=True),
    CategorySpec("Boodschappen", monthly_budget=Decimal("450.00")),
    CategorySpec("Wonen", cost_scale_type="mortgage", monthly_budget=Decimal("1450.00")),
    CategorySpec("Energie", monthly_budget=Decimal("190.00")),
    CategorySpec("Verzekeringen", cost_scale_type="insurance", monthly_budget=Decimal("160.00")),
    CategorySpec("Gemeente & heffingen", cost_scale_type="municipal", monthly_budget=Decimal("90.00")),
    CategorySpec("Vervoer", monthly_budget=Decimal("220.00")),
    CategorySpec("Abonnementen", monthly_budget=Decimal("65.00")),
    CategorySpec("Entertainment", monthly_budget=Decimal("120.00")),
    CategorySpec("Vakantie", monthly_budget=Decimal("250.00")),
)


# Maandelijks terugkerende transacties (boekt op betaalrekening)
MONTHLY_TX: tuple[TxTemplate, ...] = (
    TxTemplate("Werkgever Alex BV", Decimal("3520.00"), "Salaris", 25),
    TxTemplate("Werkgever Sam NV", Decimal("2780.00"), "Salaris", 25),
    TxTemplate("Albert Heijn", Decimal("-78.40"), "Boodschappen", 4),
    TxTemplate("Albert Heijn", Decimal("-92.15"), "Boodschappen", 11),
    TxTemplate("Jumbo", Decimal("-65.30"), "Boodschappen", 18),
    TxTemplate("Lidl", Decimal("-44.20"), "Boodschappen", 26),
    TxTemplate("ING Hypotheken", Decimal("-1280.00"), "Wonen", 1),
    TxTemplate("Vattenfall", Decimal("-185.00"), "Energie", 7),
    TxTemplate("Centraal Beheer", Decimal("-95.50"), "Verzekeringen", 5),
    TxTemplate("Univé", Decimal("-62.80"), "Verzekeringen", 5),
    TxTemplate("Gemeente Utrecht", Decimal("-87.40"), "Gemeente & heffingen", 14),
    TxTemplate("NS Reizigers", Decimal("-128.00"), "Vervoer", 2),
    TxTemplate("Shell", Decimal("-72.50"), "Vervoer", 19),
    TxTemplate("Netflix", Decimal("-13.99"), "Abonnementen", 8),
    TxTemplate("Spotify", Decimal("-10.99"), "Abonnementen", 8),
    TxTemplate("Bol.com Plus", Decimal("-2.99"), "Abonnementen", 1),
    TxTemplate("Pathé", Decimal("-32.50"), "Entertainment", 22),
    TxTemplate("Restaurant Bistro", Decimal("-68.40"), "Entertainment", 16),
)


# Eenmalige inbox-items zonder categorie (voor de badge "5 te categoriseren")
INBOX_TX: tuple[tuple[str, Decimal, int], ...] = (
    ("Bunq Cashback", Decimal("4.20"), 28),
    ("Coolblue", Decimal("-289.00"), 21),
    ("Decathlon", Decimal("-49.95"), 15),
    ("Booking.com", Decimal("-312.00"), 9),
    ("Onbekende incasso", Decimal("-17.50"), 3),
)


# ── Reset-helpers ──────────────────────────────────────────────────────────


def _reset_user(db: Session, user: User) -> None:
    """Verwijder alle records die aan deze user hangen, plus de user zelf.

    SQLite respecteert FK-cascades pas met `PRAGMA foreign_keys=ON`, dus we
    poetsen alle child-records expliciet in FK-volgorde. Postgres redt zich
    via ON DELETE CASCADE wel, maar deze code werkt op beide.
    """
    user_id = user.id

    db.query(Budget).filter_by(user_id=user_id).delete(synchronize_session=False)

    account_ids = [a.id for a in db.query(Account).filter_by(user_id=user_id).all()]
    if account_ids:
        db.query(Transaction).filter(
            Transaction.account_id.in_(account_ids)
        ).delete(synchronize_session=False)

    # Categorie-FK op transactions is al weg; nu de categorieën zelf.
    db.query(Category).filter_by(user_id=user_id).delete(synchronize_session=False)

    # Account.owners is een M2M; clear via ORM zodat de junction-rijen weg zijn.
    for acc in db.query(Account).filter_by(user_id=user_id).all():
        acc.owners = []
    db.flush()
    db.query(Account).filter_by(user_id=user_id).delete(synchronize_session=False)

    db.query(Person).filter_by(user_id=user_id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    # Bulk-deletes laten objecten in de identity map staan terwijl hun rij weg
    # is; expunge_all wist die volledig zodat de re-seed schone PK's kan
    # toewijzen zonder "identity map already had an identity for X" te raken.
    db.expunge_all()


# ── Seed-stappen ───────────────────────────────────────────────────────────


def _create_user(db: Session, username: str, password: str, email: str) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        email=email,
        is_verified=1,
        is_admin=0,  # demo is géén admin; hypotheek-toegang via GJA-47 (los)
        is_active=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_persons(db: Session, user: User) -> tuple[Person, Person]:
    alex = Person(user_id=user.id, name="Demo Alex", birthdate=date(1985, 6, 15), sort_order=0)
    sam = Person(user_id=user.id, name="Demo Sam", birthdate=date(1987, 3, 22), sort_order=1)
    db.add_all([alex, sam])
    db.commit()
    db.refresh(alex)
    db.refresh(sam)
    return alex, sam


def _create_accounts(
    db: Session, user: User, alex: Person, sam: Person
) -> dict[str, Account]:
    betaal = Account(
        user_id=user.id,
        name="Betaalrekening Alex",
        bank="ing",
        iban="NL11INGB0001112233",
    )
    spaar = Account(
        user_id=user.id,
        name="Spaarrekening",
        bank="ing",
        iban="NL12INGB0009998877",
    )
    gezamenlijk = Account(
        user_id=user.id,
        name="Gezamenlijke rekening",
        bank="rabobank",
        iban="NL13RABO0123456789",
    )
    db.add_all([betaal, spaar, gezamenlijk])
    db.commit()
    db.refresh(betaal)
    db.refresh(spaar)
    db.refresh(gezamenlijk)

    betaal.owners = [alex]
    spaar.owners = [alex, sam]
    gezamenlijk.owners = [alex, sam]
    db.commit()
    return {"betaal": betaal, "spaar": spaar, "gezamenlijk": gezamenlijk}


def _create_categories(db: Session, user: User) -> dict[str, Category]:
    by_name: dict[str, Category] = {}
    for order, spec in enumerate(CATEGORIES):
        cat = Category(
            user_id=user.id,
            name=spec.name,
            is_income=1 if spec.is_income else 0,
            cost_scale_type=spec.cost_scale_type,
            sort_order=order,
        )
        db.add(cat)
        by_name[spec.name] = cat
    db.commit()
    for cat in by_name.values():
        db.refresh(cat)
    return by_name


def _month_starts(today: date, count: int) -> Iterable[date]:
    """`count` maandstarten t/m de huidige maand, oudste eerst."""
    year = today.year
    month = today.month
    starts: list[date] = []
    for _ in range(count):
        starts.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return reversed(starts)


def _safe_day(year: int, month: int, day: int) -> date:
    """Klem `day` aan de laatste dag van de maand (28..31 vs feb)."""
    from calendar import monthrange

    last = monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _create_transactions(
    db: Session, accounts: dict[str, Account], categories: dict[str, Category], today: date,
) -> int:
    betaal = accounts["betaal"]
    count = 0

    for month_start in _month_starts(today, 12):
        for tpl in MONTHLY_TX:
            tx_date = _safe_day(month_start.year, month_start.month, tpl.day)
            if tx_date > today:
                continue
            tag = f"{month_start.isoformat()}-{tpl.counterparty}-{tpl.amount}"
            import_hash = hashlib.sha256(tag.encode()).hexdigest()
            db.add(Transaction(
                account_id=betaal.id,
                date=tx_date,
                amount=tpl.amount,
                currency="EUR",
                description=f"Demo: {tpl.counterparty}",
                counterparty=tpl.counterparty,
                category_id=categories[tpl.category].id,
                import_hash=import_hash,
                is_reviewed=1,
            ))
            count += 1

    # Inbox-items: huidige maand, geen categorie → komen op /inbox.
    for counterparty, amount, day in INBOX_TX:
        tx_date = _safe_day(today.year, today.month, day)
        if tx_date > today:
            tx_date = today
        tag = f"inbox-{counterparty}-{amount}"
        import_hash = hashlib.sha256(tag.encode()).hexdigest()
        db.add(Transaction(
            account_id=betaal.id,
            date=tx_date,
            amount=amount,
            currency="EUR",
            description=f"Demo inbox: {counterparty}",
            counterparty=counterparty,
            category_id=None,
            import_hash=import_hash,
            is_reviewed=0,
        ))
        count += 1

    db.commit()
    return count


def _create_budgets(
    db: Session, user: User, categories: dict[str, Category], today: date,
) -> int:
    count = 0
    for month_start in _month_starts(today, 12):
        for spec in CATEGORIES:
            if spec.monthly_budget is None:
                continue
            db.add(Budget(
                user_id=user.id,
                category_id=categories[spec.name].id,
                year=month_start.year,
                month=month_start.month,
                amount=spec.monthly_budget,
            ))
            count += 1
    db.commit()
    return count


# ── Publieke API ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SeedResult:
    user_id: int
    username: str
    tx_count: int
    budget_count: int
    category_count: int
    account_count: int
    person_count: int


def seed_demo_user(
    *,
    username: str = DEFAULT_USERNAME,
    password: str = DEFAULT_PASSWORD,
    email: str = DEFAULT_EMAIL,
    today: date | None = None,
    db: Session | None = None,
) -> SeedResult:
    """Maak (of reset) de demo-user. Retourneert teller-overzicht.

    Wordt aangeroepen vanuit `app.routers.admin` achter de admin-guard.
    """
    today = today or date.today()
    own_session = db is None
    db = db or SessionLocal()
    try:
        # Stale identity-map entries volledig wegpoetsen om PK-collision
        # warnings te voorkomen wanneer SQLite dezelfde IDs hergebruikt.
        db.expunge_all()
        existing = db.query(User).filter(User.username == username).first()
        if existing is not None:
            _reset_user(db, existing)

        user = _create_user(db, username, password, email)
        alex, sam = _create_persons(db, user)
        accounts = _create_accounts(db, user, alex, sam)
        categories = _create_categories(db, user)
        tx_count = _create_transactions(db, accounts, categories, today)
        budget_count = _create_budgets(db, user, categories, today)

        return SeedResult(
            user_id=user.id,
            username=user.username,
            tx_count=tx_count,
            budget_count=budget_count,
            category_count=len(categories),
            account_count=len(accounts),
            person_count=2,
        )
    finally:
        if own_session:
            db.close()
