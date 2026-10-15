"""ACT-53a: verwachting per persoon (betaalrekeningen + mijlpaal 18 jaar)."""
import datetime
from decimal import Decimal

from app.auth import hash_password
from app.models import Account, Person, RecurringTransaction, Transaction, User
from app.person_forecast import add_months, build_person_forecast, months_until

TODAY = datetime.date(2026, 10, 15)
D = Decimal


def _world(db):
    user = User(username="pf", email="pf@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    nel = Person(user_id=user.id, name="Nelleke", sort_order=0)
    gj = Person(user_id=user.id, name="Gerd-Jan", sort_order=1)
    kid = Person(user_id=user.id, name="Hannah", sort_order=2, birthdate=datetime.date(2010, 12, 5))
    db.add_all([nel, gj, kid])
    db.flush()
    joint = Account(user_id=user.id, name="Samen", bank="abn_amro", kind="payment", iban="NL91ABNA0417164300")
    own = Account(user_id=user.id, name="Privé", bank="bunq", kind="payment")
    spaar = Account(user_id=user.id, name="Spaar", bank="bunq", kind="savings", iban="NL81BUNQ2088619097")
    db.add_all([joint, own, spaar])
    db.flush()
    joint.owners = [nel, gj]
    own.owners = [gj]
    spaar.owners = [gj]
    db.add_all([
        Transaction(account_id=joint.id, date=TODAY, amount=D("-10"), balance_after=D("1000"), import_hash="a"),
        Transaction(account_id=own.id, date=TODAY, amount=D("-5"), balance_after=D("200"), import_hash="b"),
    ])
    db.add_all([
        RecurringTransaction(user_id=user.id, account_id=joint.id, name="Salaris", amount_expected=D("2000"),
                             frequency="monthly"),
        RecurringTransaction(user_id=user.id, account_id=joint.id, name="Huur", amount_expected=D("-900"),
                             frequency="monthly"),
        RecurringTransaction(user_id=user.id, account_id=own.id, name="Sparen", amount_expected=D("-100"),
                             frequency="monthly", counterparty="NL81 BUNQ 2088 6190 97"),
        RecurringTransaction(user_id=user.id, account_id=joint.id, name="Verzekering", amount_expected=D("-120"),
                             frequency="quarterly", active_months="1,4,7,10"),
    ])
    db.commit()
    return user, nel, gj, kid


def test_shared_account_is_split_and_savings_transfer_separated(db):
    user, nel, gj, _ = _world(db)
    nelleke = build_person_forecast(db, user.id, nel.id, 3, today=TODAY)
    # Nelleke: helft van de gezamenlijke rekening, niets van de privérekening
    assert nelleke["start_balance"] == D("500")
    first = nelleke["rows"][0]            # november 2026
    assert first["month"] == datetime.date(2026, 11, 1)
    assert first["income"] == D("1000") and first["expenses"] == D("-450") and first["to_savings"] == D("0")
    assert first["balance"] == D("1050")

    gerd = build_person_forecast(db, user.id, gj.id, 3, today=TODAY)
    assert gerd["start_balance"] == D("700")          # 500 + 200
    row = gerd["rows"][0]
    assert row["to_savings"] == D("-100")             # spaaropdracht apart
    assert row["net"] == D("1000") - D("450") - D("100")


def test_active_months_are_respected_and_minimum_is_tracked(db):
    user, nel, _, _ = _world(db)
    forecast = build_person_forecast(db, user.id, nel.id, 6, today=TODAY)
    months = {r["month"].month: r for r in forecast["rows"]}
    assert months[1]["expenses"] == D("-510")          # januari: huur + kwartaalpost (helft)
    assert months[11]["expenses"] == D("-450")         # november: alleen huur
    assert forecast["min_balance"] == forecast["rows"][0]["balance"] or forecast["min_balance"] <= forecast["rows"][0]["balance"]


def test_milestone_for_child_and_unknown_person(db):
    user, _, _, kid = _world(db)
    forecast = build_person_forecast(db, user.id, kid.id, 12, today=TODAY)
    milestone = forecast["milestone"]
    assert milestone["date"] == datetime.date(2028, 12, 5)
    assert milestone["months_left"] == 26 and milestone["reached"] is False
    assert build_person_forecast(db, user.id + 99, kid.id, 12, today=TODAY) is None


def test_month_helpers():
    assert add_months(datetime.date(2026, 11, 20), 3) == datetime.date(2027, 2, 1)
    assert months_until(datetime.date(2028, 12, 5), TODAY) == 26



def test_person_page_renders_for_all_periods_and_scopes_to_the_user(db):
    from fastapi.testclient import TestClient

    from app.auth import create_session_cookie
    from app.main import app

    user, nel, _, kid = _world(db)
    other = User(username="other", email="o@example.test", password_hash=hash_password("pw"))
    db.add(other)
    db.commit()
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    for period in (3, 6, 12, 24, 36, 60):
        page = client.get(f"/persons/{nel.id}?period={period}")
        assert page.status_code == 200 and "Nelleke" in page.text
    assert "Naar 18 jaar" in client.get(f"/persons/{kid.id}").text
    assert client.get("/persons/999").status_code == 404
    other_client = TestClient(app)
    other_client.cookies.set("session", create_session_cookie(other.id))
    assert other_client.get(f"/persons/{nel.id}").status_code == 404
