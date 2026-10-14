"""ACT-44: spaarberekeningen: één pure saldo-functie, één query voor de categorietotalen, geen dode route."""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import event

from app import clock
from app.auth import create_session_cookie, hash_password
from app.database import engine
from app.main import app
from app.models import Account, Category, SavingsEntry, SavingsLine, SavingsPlan, Transaction, User
from app.routers.savings import _compute_december_balance, _get_transaction_totals_by_month
from app.savings_calc import running_balances
from app.savings_service import transaction_totals_by_category

D = Decimal


class _Entry:
    def __init__(self, month, amount):
        self.month, self.amount = month, amount


class _Line:
    def __init__(self, id, is_income, entries):
        self.id, self.is_income, self.entries = id, is_income, entries


def test_running_balances_income_adds_expense_subtracts_and_actuals_win():
    income = _Line(1, True, [_Entry(1, D("1000")), _Entry(2, D("1000"))])
    rent = _Line(2, False, [_Entry(1, D("-400")), _Entry(2, D("400")), _Entry(3, None)])   # tekens maken niet uit
    plain = running_balances(D("50"), [income, rent])
    assert plain[1] == D("650") and plain[2] == D("1250") and plain[12] == D("1250")

    with_actuals = running_balances(D("50"), [income, rent], {2: {2: D("-450")}})          # werkelijk wint
    assert with_actuals[2] == D("1200")
    assert running_balances(D("0"), []) == {m: D("0") for m in range(1, 13)}


def _world(db, category_lines=6):
    year = clock.today_nl().year
    user = User(username="savings-user", password_hash=hash_password("x" * 10))
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="Spaar", bank="x")
    db.add(account)
    db.flush()
    plan = SavingsPlan(user_id=user.id, account_id=account.id, year=year, starting_balance=D("100"))
    db.add(plan)
    db.flush()
    categories = [Category(user_id=user.id, account_id=account.id, name=f"C{i}") for i in range(category_lines)]
    db.add_all(categories)
    db.flush()
    for i, category in enumerate(categories):
        line = SavingsLine(plan_id=plan.id, name=f"L{i}", category_id=category.id, is_income=1 if i == 0 else 0)
        db.add(line)
        db.flush()
        for month in (1, 2, 3):
            db.add(SavingsEntry(line_id=line.id, month=month, amount=D("100")))
            db.add(Transaction(account_id=account.id, date=date(year, month, 5), amount=D("-60") - i,
                               category_id=category.id, description="x", import_hash=f"h{i}-{month}"))
    db.commit()
    return user, account, plan, categories


@contextmanager
def count_transaction_queries():
    seen = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM transactions" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_batch_totals_equal_the_per_category_helper(db):
    user, account, plan, categories = _world(db)
    batch = transaction_totals_by_category(db, account.id, plan.year, [c.id for c in categories])
    for category in categories:
        assert batch[category.id] == _get_transaction_totals_by_month(db, account.id, plan.year, category.id)
    assert transaction_totals_by_category(db, account.id, plan.year, []) == {}


def test_december_balance_matches_a_naive_reference_and_uses_one_transaction_query(db):
    user, account, plan, categories = _world(db, category_lines=8)
    plan = db.get(SavingsPlan, plan.id)

    # Referentie: de oorspronkelijke geneste lussen met een query per lijn en maand.
    balance = plan.starting_balance or D("0")
    for month in range(1, 13):
        for line in plan.lines:
            entry = next((e for e in line.entries if e.month == month), None)
            amount = entry.amount if entry else None
            actual = _get_transaction_totals_by_month(db, plan.account_id, plan.year, line.category_id).get(month)
            if actual is not None:
                amount = actual
            if amount is None:
                continue
            balance += abs(amount) if line.is_income else -abs(amount)

    with count_transaction_queries() as queries:
        result = _compute_december_balance(db, plan)
    assert result == balance
    assert len(queries) == 1                                         # was: 12 maanden x 8 lijnen = 96


def test_cell_update_has_a_bounded_number_of_transaction_queries(db):
    user, account, plan, categories = _world(db, category_lines=8)
    next_plan = SavingsPlan(user_id=user.id, account_id=account.id, year=plan.year + 1,
                            source_plan_id=plan.id, starting_balance=D("0"))
    db.add(next_plan)
    db.flush()
    line = SavingsLine(plan_id=next_plan.id, name="Vrij", is_income=0, frequency="custom")
    db.add(line)
    db.flush()
    entry = SavingsEntry(line_id=line.id, month=12, amount=D("10"))
    db.add(entry)
    db.commit()
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    with count_transaction_queries() as queries:
        response = client.post("/savings/entries/update", data={"entry_id": entry.id, "amount": "25"})
    assert response.status_code == 200, response.text
    assert len(queries) <= 2                                         # decembersaldo van het bronplan, één query


def test_custom_line_form_still_parses_the_twelve_month_fields(db):
    user, account, plan, categories = _world(db, category_lines=1)
    empty = Category(user_id=user.id, account_id=account.id, name="Zonder transacties")   # anders vult de route uit transacties
    db.add(empty)
    db.commit()
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    data = {"plan_id": plan.id, "name": "Onregelmatig", "category_id": empty.id, "frequency": "custom",
            "amount_3": "100", "amount_9": "50,5"}
    response = client.post("/savings/lines", data=data)
    assert response.status_code == 302
    db.expire_all()
    line = db.query(SavingsLine).filter_by(name="Onregelmatig").one()
    amounts = {e.month: e.amount for e in line.entries if e.amount is not None}
    assert amounts == {3: D("100"), 9: D("50.5")}


def test_the_dead_accept_suggestion_route_is_gone(db):
    user, account, plan, categories = _world(db, category_lines=1)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    assert client.post(f"/savings/{plan.id}/accept-suggestion", data={}).status_code in (404, 405)
