"""Tests voor het kapitaal-dashboard (GJA-18): sparen + beleggen per persoon."""
import datetime
import os
import tempfile
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.capital_dashboard import build_capital_dashboard
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    Account,
    Person,
    PortfolioAsset,
    PortfolioHolding,
    SavingsEntry,
    SavingsLine,
    SavingsPlan,
    User,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        # Wipe tables in FK-safe order
        db.query(SavingsEntry).delete()
        db.query(SavingsLine).delete()
        db.query(SavingsPlan).delete()
        db.query(PortfolioHolding).delete()
        db.query(PortfolioAsset).delete()
        # account_owners is a secondary table — clearing Accounts cascades.
        for acc in db.query(Account).all():
            acc.owners = []
        db.commit()
        db.query(Account).delete()
        db.query(Person).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _make_user(db, username="alice"):
    u = User(username=username, email=f"{username}@x.nl", password_hash=hash_password("pw"))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_person(db, user, name="Gerd"):
    p = Person(user_id=user.id, name=name)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_account(db, user, owners, name="Spaar", bank="bunq", iban=None):
    acc = Account(user_id=user.id, name=name, bank=bank, iban=iban)
    acc.owners = list(owners)
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _make_plan_with_monthly_net(
    db, user, account, year, starting_balance, monthly_income, monthly_expense,
):
    """Handige helper: maakt een plan met één income-lijn en één expense-lijn,
    beide met een bedrag in elke maand. Eindsaldo = start + 12 * (inc - exp)."""
    plan = SavingsPlan(
        user_id=user.id,
        account_id=account.id,
        year=year,
        starting_balance=Decimal(str(starting_balance)),
    )
    db.add(plan)
    db.flush()
    inc_line = SavingsLine(
        plan_id=plan.id, name="Inkomsten", is_income=1,
        annual_budget=Decimal("0"), frequency="monthly",
        default_amount=Decimal(str(monthly_income)),
    )
    exp_line = SavingsLine(
        plan_id=plan.id, name="Uitgaven", is_income=0,
        annual_budget=Decimal("0"), frequency="monthly",
        default_amount=Decimal(str(monthly_expense)),
    )
    db.add_all([inc_line, exp_line])
    db.flush()
    for m in range(1, 13):
        db.add(SavingsEntry(line_id=inc_line.id, month=m,
                            amount=Decimal(str(monthly_income)), status="forecast"))
        db.add(SavingsEntry(line_id=exp_line.id, month=m,
                            amount=Decimal(str(monthly_expense)), status="forecast"))
    db.commit()
    db.refresh(plan)
    return plan


def _make_asset(db, user, name="Goud", price=Decimal("100"),
                growth_pct=Decimal("0"), fee_pct=Decimal("0"),
                fee_fixed=Decimal("0")):
    a = PortfolioAsset(
        user_id=user.id, name=name, symbol=name[:3].upper(),
        asset_class="metal", unit="oz",
        current_price_eur=price, monthly_growth_pct=growth_pct,
        cashout_fee_pct=fee_pct, cashout_fee_fixed_eur=fee_fixed,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_holding(db, user, asset, person, qty=Decimal("10"),
                  contrib=Decimal("0")):
    h = PortfolioHolding(
        user_id=user.id, asset_id=asset.id, person_id=person.id,
        quantity=qty, monthly_contribution_eur=contrib,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def _login_client(user_id):
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user_id))
    return client


# ── Pure calculation tests ────────────────────────────────────────────

def test_dashboard_empty_user_renders_with_zero_totals(db_session):
    alice = _make_user(db_session)
    data = build_capital_dashboard(db_session, alice.id)
    assert data["persons"] == []
    assert data["series_samen"] == [0.0] * 13
    assert data["samen_totals"]["total_gross"] == Decimal("0")


def test_dashboard_person_only_savings(db_session):
    alice = _make_user(db_session)
    gerd = _make_person(db_session, alice)
    acc = _make_account(db_session, alice, owners=[gerd], name="Oranje")
    today = datetime.date(2026, 4, 20)
    # Start 1000, maandelijks 500 in - 200 uit = +300/mnd
    _make_plan_with_monthly_net(
        db_session, alice, acc, today.year,
        starting_balance=1000, monthly_income=500, monthly_expense=200,
    )

    data = build_capital_dashboard(db_session, alice.id, today=today)
    totals = data["current_totals"][gerd.id]
    # Huidig saldo = 1000 + 4 * 300 = 2200 (na maanden 1..4)
    assert totals["savings"] == Decimal("2200")
    assert totals["portfolio_gross"] == Decimal("0")
    # Projectie: vanaf apr (2200) nog 8 maanden +300 tot dec (4600),
    # daarna vlak (geen plan volgend jaar). +12m = 4600.
    series = data["series_per_person"][gerd.id]
    assert series[0] == 2200.0
    assert series[8] == 4600.0  # dec
    assert series[-1] == 4600.0


def test_dashboard_person_only_portfolio(db_session):
    alice = _make_user(db_session)
    gerd = _make_person(db_session, alice)
    asset = _make_asset(db_session, alice, price=Decimal("100"), growth_pct=Decimal("0"))
    _make_holding(db_session, alice, asset, gerd, qty=Decimal("10"), contrib=Decimal("50"))

    data = build_capital_dashboard(db_session, alice.id)
    t = data["current_totals"][gerd.id]
    assert t["savings"] == Decimal("0")
    assert t["portfolio_gross"] == Decimal("1000")
    # 12 maanden × 50/mnd = 600 extra
    series = data["series_per_person"][gerd.id]
    assert series[0] == 1000.0
    assert series[-1] == 1600.0


def test_dashboard_combines_savings_and_portfolio(db_session):
    alice = _make_user(db_session)
    gerd = _make_person(db_session, alice)
    acc = _make_account(db_session, alice, owners=[gerd])
    today = datetime.date(2026, 4, 20)
    _make_plan_with_monthly_net(
        db_session, alice, acc, today.year,
        starting_balance=500, monthly_income=300, monthly_expense=100,
    )
    asset = _make_asset(db_session, alice, price=Decimal("50"))
    _make_holding(db_session, alice, asset, gerd, qty=Decimal("4"))

    data = build_capital_dashboard(db_session, alice.id, today=today)
    t = data["current_totals"][gerd.id]
    # sparen nu: 500 + 4 * 200 = 1300; beleggen: 200 → totaal 1500
    assert t["savings"] == Decimal("1300")
    assert t["portfolio_gross"] == Decimal("200")
    assert t["total_gross"] == Decimal("1500")


def test_dashboard_samen_equals_sum_of_persons(db_session):
    alice = _make_user(db_session)
    gerd = _make_person(db_session, alice, "Gerd")
    roos = _make_person(db_session, alice, "Roos")
    acc = _make_account(db_session, alice, owners=[gerd, roos])
    today = datetime.date(2026, 4, 20)
    _make_plan_with_monthly_net(
        db_session, alice, acc, today.year,
        starting_balance=2000, monthly_income=0, monthly_expense=0,
    )
    asset = _make_asset(db_session, alice, price=Decimal("10"))
    _make_holding(db_session, alice, asset, gerd, qty=Decimal("100"))
    _make_holding(db_session, alice, asset, roos, qty=Decimal("50"))

    data = build_capital_dashboard(db_session, alice.id, today=today)
    sum_gross = (
        data["current_totals"][gerd.id]["total_gross"]
        + data["current_totals"][roos.id]["total_gross"]
    )
    assert data["samen_totals"]["total_gross"] == sum_gross


def test_shared_account_splits_equally(db_session):
    """Spaarrekening met twee eigenaren wordt 50/50 gesplitst per persoon."""
    alice = _make_user(db_session)
    gerd = _make_person(db_session, alice, "Gerd")
    roos = _make_person(db_session, alice, "Roos")
    acc = _make_account(db_session, alice, owners=[gerd, roos])
    today = datetime.date(2026, 4, 20)
    _make_plan_with_monthly_net(
        db_session, alice, acc, today.year,
        starting_balance=2000, monthly_income=0, monthly_expense=0,
    )
    data = build_capital_dashboard(db_session, alice.id, today=today)
    assert data["current_totals"][gerd.id]["savings"] == Decimal("1000")
    assert data["current_totals"][roos.id]["savings"] == Decimal("1000")


def test_net_value_applies_cashout_fee(db_session):
    alice = _make_user(db_session)
    gerd = _make_person(db_session, alice)
    asset = _make_asset(db_session, alice, price=Decimal("100"),
                        fee_pct=Decimal("5"), fee_fixed=Decimal("10"))
    _make_holding(db_session, alice, asset, gerd, qty=Decimal("10"))
    # gross = 1000, net = 1000 - 50 - 10 = 940
    data = build_capital_dashboard(db_session, alice.id)
    t = data["current_totals"][gerd.id]
    assert t["portfolio_gross"] == Decimal("1000")
    assert t["portfolio_net"] == Decimal("940")


def test_no_plan_means_savings_flat_at_zero(db_session):
    """Een account zonder plan voor het huidige jaar: saldo 0, vlakke lijn."""
    alice = _make_user(db_session)
    gerd = _make_person(db_session, alice)
    _make_account(db_session, alice, owners=[gerd], name="Onbekend")

    data = build_capital_dashboard(db_session, alice.id)
    assert data["current_totals"][gerd.id]["savings"] == Decimal("0")
    assert data["series_per_person"][gerd.id] == [0.0] * 13


def test_account_without_owners_is_skipped(db_session):
    """Een spaarrekening zonder eigenaren telt niet mee in Samen."""
    alice = _make_user(db_session)
    acc = _make_account(db_session, alice, owners=[], name="Weesrekening")
    _make_plan_with_monthly_net(
        db_session, alice, acc, 2026,
        starting_balance=500, monthly_income=0, monthly_expense=0,
    )
    data = build_capital_dashboard(db_session, alice.id)
    # Geen personen → geen bijdrage aan Samen
    assert data["samen_totals"]["savings"] == Decimal("0")


def test_labels_wrap_year_when_needed(db_session):
    alice = _make_user(db_session)
    # Start in oktober — +12m gaat naar okt volgend jaar
    today = datetime.date(2026, 10, 15)
    data = build_capital_dashboard(db_session, alice.id, today=today)
    labels = data["labels"]
    assert len(labels) == 13
    assert labels[0] == "Okt"
    # Laatste punt is okt van volgend jaar → bevat jaar-suffix
    assert "'27" in labels[-1]


# ── HTTP route tests ──────────────────────────────────────────────────

def test_dashboard_route_requires_login(db_session):
    client = TestClient(app)
    resp = client.get("/portfolio/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 401, 303)


def test_dashboard_route_renders_for_logged_in_user(db_session):
    alice = _make_user(db_session)
    _make_person(db_session, alice)
    client = _login_client(alice.id)
    resp = client.get("/portfolio/dashboard")
    assert resp.status_code == 200
    assert "Kapitaal-dashboard" in resp.text
    assert "capitalChart" in resp.text


def test_dashboard_filter_selects_person(db_session):
    alice = _make_user(db_session)
    gerd = _make_person(db_session, alice, "Gerd")
    client = _login_client(alice.id)
    resp = client.get(f"/portfolio/dashboard?person={gerd.id}")
    assert resp.status_code == 200
    # De gekozen persoonsnaam moet als chart-label opduiken
    assert "Gerd" in resp.text


def test_dashboard_unknown_person_falls_back_to_samen(db_session):
    alice = _make_user(db_session)
    _make_person(db_session, alice)
    client = _login_client(alice.id)
    resp = client.get("/portfolio/dashboard?person=99999")
    assert resp.status_code == 200
    # Default-tekst voor Samen zit in de pagina
    assert "Alle personen gecombineerd" in resp.text
