"""ACT-51: HTTP-vangnet voor het UI-redesign: elke pagina rendert met realistische data.

Een redesign raakt 65 templates; deze test faalt zodra een pagina na een templatewijziging een 500 geeft,
leeg terugkomt of een verwijzing mist. Hij controleert bewust alleen "rendert netjes", niet de inhoud.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import (
    Account, Budget, Category, HouseholdFinance, ImportBatch, MortgageScenario, NetWorthAccount, Person,
    PortfolioAsset, PortfolioHolding, RecurringTransaction, Rule, SavingsEntry, SavingsLine, SavingsPlan,
    Transaction, User,
)

D = Decimal


@pytest.fixture
def world(db, monkeypatch):
    today = clock.today_nl()
    user = User(username="smoke-admin", password_hash=hash_password("x" * 10), is_admin=1, can_access_mortgage=1)
    db.add(user)
    db.flush()
    monkeypatch.setattr("app.auth.SUPER_ADMIN_USERNAME", user.username)

    person = Person(user_id=user.id, name="Gerd-Jan", sort_order=0)
    db.add(person)
    checking = Account(user_id=user.id, name="Betaal", bank="abn_amro", iban="NL91ABNA0417164300", kind="payment")
    savings = Account(user_id=user.id, name="Spaar", bank="bunq", iban="NL81BUNQ2088619097", kind="savings")
    db.add_all([checking, savings])
    db.flush()
    checking.owners = [person]

    parent = Category(user_id=user.id, name="Wonen", color="#89b4fa")
    income = Category(user_id=user.id, name="Inkomen", is_income=1)
    db.add_all([parent, income])
    db.flush()
    child = Category(user_id=user.id, name="Energie", parent_id=parent.id)
    db.add(child)
    db.flush()

    def tx(n, account, day, amount, category=None, **extra):
        return Transaction(account_id=account.id, date=day, amount=D(amount), description=f"Omschrijving {n}",
                           counterparty=f"Tegenpartij {n}", import_hash=f"smoke-{n}",
                           category_id=category.id if category else None, **extra)

    transactions = [tx(i, checking, today.replace(day=1) - timedelta(days=i * 9), "-25.00" if i % 2 else "-80.00",
                       child if i % 3 else None) for i in range(1, 14)]
    transactions.append(tx(100, checking, today.replace(day=1), "2500.00", income))
    transactions.append(tx(101, savings, today.replace(day=1), "300.00"))
    db.add_all(transactions)
    db.flush()

    item = RecurringTransaction(user_id=user.id, account_id=checking.id, name="Huur", amount_expected=D("-900"),
                                frequency="monthly", is_active=1, counterparty="Verhuurder", category_id=parent.id,
                                start_date=date(today.year - 1, 1, 1))
    db.add(item)
    db.add(Rule(user_id=user.id, name="Energie", match_field="counterparty", match_type="contains",
                match_value="Tegenpartij 3", assign_category_id=child.id))
    db.add(Budget(user_id=user.id, category_id=child.id, year=today.year, month=today.month, amount=D("150")))
    db.add(ImportBatch(user_id=user.id, account_id=checking.id, source="csv:abn", total_count=3, imported_count=3))

    plan = SavingsPlan(user_id=user.id, account_id=checking.id, year=today.year, starting_balance=D("100"))
    db.add(plan)
    db.flush()
    line = SavingsLine(plan_id=plan.id, name="Energie", category_id=child.id, is_income=0, default_amount=D("100"))
    db.add(line)
    db.flush()
    db.add_all([SavingsEntry(line_id=line.id, month=m, amount=D("100")) for m in range(1, 13)])

    asset = PortfolioAsset(user_id=user.id, name="Goud", symbol="XAU", asset_class="metal", unit="oz",
                           current_price_eur=D("2000"))
    db.add(asset)
    db.flush()
    db.add(PortfolioHolding(user_id=user.id, asset_id=asset.id, person_id=person.id, quantity=D("2"), monthly_contribution_eur=D("50")))
    db.add(NetWorthAccount(user_id=user.id, name="Huis", account_type="asset", category="vastgoed", balance=D("400000")))
    db.add(HouseholdFinance(user_id=user.id))
    db.add(MortgageScenario(user_id=user.id, name="Nieuw huis", valuation=D("500000"), offer=D("480000")))
    db.commit()

    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    return client, {"plan": plan.id, "account": checking.id, "tx": transactions[0].id, "line": line.id}


def _get_paths():
    schema = app.openapi()["paths"]
    return sorted(p for p, ops in schema.items() if "get" in ops and "{" not in p)


# /admin/imports gebruikt PostgreSQL-only SQL (date_trunc) en kan niet op SQLite draaien.
SKIP = {"/logout", "/auth/google", "/auth/google/callback", "/export", "/settings/export", "/admin/imports"}


def test_every_parameterless_get_page_renders_without_a_server_error(world):
    client, ids = world
    problems, rendered = [], 0
    for path in _get_paths():
        if path in SKIP or path.startswith("/static"):
            continue
        response = client.get(path)
        if response.status_code >= 500:
            problems.append(f"{path} -> {response.status_code}")
        elif response.status_code == 200 and "text/html" in response.headers.get("content-type", ""):
            rendered += 1
            if "</html>" not in response.text:
                problems.append(f"{path} -> geen volledige pagina")
    assert problems == []
    assert rendered >= 30                                       # er worden echt veel pagina's gerenderd


def test_detail_pages_render(world):
    client, ids = world
    for path in (f"/savings/{ids['plan']}", f"/transactions/{ids['tx']}/edit", f"/accounts/{ids['account']}/merge",
                 "/transactions?month=&uncategorized=1", f"/transactions?account_id={ids['account']}",
                 f"/budgets?account_id={ids['account']}", "/dashboard?month=1", "/categories?show_archived=1",
                 "/analytics", "/recurring", "/inbox", "/portfolio", "/persons", "/hypotheek/scenarios"):
        response = client.get(path)
        assert response.status_code in (200, 302), (path, response.status_code)
        if response.status_code == 200:
            assert "</html>" in response.text, path
