"""bunq-synchronisatie (ACT-31b): betalingen, dubbelcheck tegen CSV, overboekingen en routes."""
import os
import tempfile
from datetime import date
from decimal import Decimal

import pytest

_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient

import app.routers.bunq as bunq_router
from app.auth import create_session_cookie
from app.bunq_client import BunqClient, parse_payment
from app.bunq_sync import sync_connection
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    Account, BunqAccountLink, BunqConnection, ImportBatch, Transaction, User,
)

API_KEY = "sandbox_0123456789abcdef0123456789abcdef"


def payment(pid, created, value, desc="", name="Winkel", iban=None):
    return {"Payment": {
        "id": pid, "created": created, "amount": {"value": value, "currency": "EUR"},
        "description": desc, "counterparty_alias": {"display_name": name, "iban": iban},
    }}


class FakeBunq:
    """Replays bunq. `pages[account_id]` is a list of pages, newest first."""

    def __init__(self, pages):
        self.pages = pages
        self.payment_calls = []

    def request(self, method, url, headers=None, data=None, timeout=None):
        from tests.test_bunq_client import FakeResponse
        path = url.split("/v1", 1)[1]
        if path == "/installation":
            return FakeResponse(200, {"Response": [{"Token": {"token": "inst"}}]})
        if path == "/device-server":
            return FakeResponse(200, {"Response": [{"Id": {"id": 1}}]})
        if path == "/session-server":
            return FakeResponse(200, {"Response": [{"Token": {"token": "sess"}}, {"UserPerson": {"id": 77}}]})
        if "/payment" in path:
            self.payment_calls.append(path)
            account_id = int(path.split("/monetary-account/")[1].split("/")[0])
            pages = self.pages[account_id]
            index = 0
            if "older_id=" in path:
                index = int(path.split("older_id=")[1].split("&")[0])
            body = {"Response": pages[index]}
            if index + 1 < len(pages):
                body["Pagination"] = {"older_url": f"/v1/user/77/monetary-account/{account_id}/payment?count=200&older_id={index + 1}"}
            else:
                body["Pagination"] = {"older_url": None}
            return FakeResponse(200, body)
        if "/monetary-account" in path:
            return FakeResponse(200, {"Response": [{"MonetaryAccountBank": {
                "id": 1, "description": "Main", "status": "ACTIVE",
                "balance": {"value": "1.00", "currency": "EUR"},
                "alias": [{"type": "IBAN", "value": "NL01BUNQ0000000001"}]}}]})
        raise AssertionError(path)


@pytest.fixture(autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _world(db, enabled=True):
    user = User(username="bunq-sync", password_hash="x")
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="Bunq Samen spaar", bank="bunq", iban="NL01BUNQ0000000001")
    db.add(account)
    connection = BunqConnection(user_id=user.id, api_key=API_KEY)
    db.add(connection)
    db.flush()
    link = BunqAccountLink(connection_id=connection.id, bunq_account_id=1, description="Main",
                           iban="NL01BUNQ0000000001", bunq_kind="MonetaryAccountBank",
                           bunq_status="ACTIVE", enabled=1 if enabled else 0, account_id=account.id)
    db.add(link)
    db.flush()
    return user, account, connection, link


def _client(fake):
    return BunqClient("https://api.bunq.test/v1", http=fake)


def test_parse_payment_uses_amsterdam_date_and_skips_garbage():
    p = parse_payment(payment(5, "2026-05-01 23:30:00.000000", "-3.50", "koffie")["Payment"])
    assert p.booked_on == date(2026, 5, 2) and p.amount == Decimal("-3.50")  # 23:30 UTC is na middernacht in NL
    assert parse_payment({"id": 1}) is None


def test_list_payments_follows_pages_and_stops_at_known_id():
    pages = {1: [[payment(9, "2026-05-03 10:00:00", "-1.00")], [payment(8, "2026-05-02 10:00:00", "-1.00"),
                                                              payment(7, "2026-05-01 10:00:00", "-1.00")]]}
    fake = FakeBunq(pages)
    client = _client(fake)
    session = client.connect(API_KEY)
    assert [p.id for p in client.list_payments(session, 1, pause=lambda s: None)] == [9, 8, 7]
    assert [p.id for p in client.list_payments(session, 1, newer_than_id=7, pause=lambda s: None)] == [9, 8]


def test_sync_skips_csv_rows_keeps_identical_payments_and_is_incremental(db):
    user, account, connection, link = _world(db)
    db.add(Transaction(account_id=account.id, date=date(2026, 5, 1), amount=Decimal("-10.00"),
                       counterparty="Albert Heijn", description="csv", import_hash="csv-1"))
    db.flush()
    pages = {1: [[
        payment(3, "2026-05-03 10:00:00", "-3.00", "koffie", "Bar"),
        payment(2, "2026-05-03 11:00:00", "-3.00", "koffie", "Bar"),   # identiek, ander id
        payment(1, "2026-05-01 10:00:00", "-10.00", "AH", "ALBERT HEIJN"),  # staat al via CSV
    ]]}
    fake = FakeBunq(pages)

    reports = sync_connection(db, connection, _client(fake), dry_run=False)
    db.commit()
    r = reports[0]
    assert (r.fetched, r.new, r.matched_existing) == (3, 2, 1)
    assert db.query(Transaction).filter_by(account_id=account.id).count() == 3  # CSV + 2 koffies
    assert db.query(ImportBatch).filter_by(source="bunq").one().imported_count == 2
    assert db.get(BunqAccountLink, link.id).last_payment_id == 3

    # Tweede run: niets nieuws, en alleen nieuwere betalingen worden verwerkt.
    pages[1] = [[payment(4, "2026-05-04 10:00:00", "-3.00", "koffie", "Bar")] + pages[1][0]]
    reports = sync_connection(db, connection, _client(FakeBunq(pages)), dry_run=False)
    db.commit()
    assert (reports[0].fetched, reports[0].new) == (1, 1)  # ook al lijkt hij op eerdere bunq-koffies
    assert db.query(Transaction).filter_by(account_id=account.id).count() == 4


def test_dry_run_stores_nothing(db):
    user, account, connection, link = _world(db)
    pages = {1: [[payment(1, "2026-05-01 10:00:00", "-10.00", "AH", "Albert Heijn")]]}
    reports = sync_connection(db, connection, _client(FakeBunq(pages)), dry_run=True)
    db.commit()
    assert reports[0].new == 1
    assert db.query(Transaction).count() == 0
    assert db.get(BunqAccountLink, link.id).last_payment_id is None


def test_transfers_between_own_accounts_are_linked(db):
    user, account, connection, link = _world(db)
    abn = Account(user_id=user.id, name="ABN", bank="abn_amro", iban="NL45ABNA0503737143")
    db.add(abn)
    db.flush()
    outgoing = Transaction(account_id=abn.id, date=date(2026, 5, 1), amount=Decimal("-250.00"),
                           counterparty="Bunq", counterparty_iban="NL01BUNQ0000000001",
                           description="sparen", import_hash="abn-1")
    db.add(outgoing)
    db.flush()
    pages = {1: [[payment(1, "2026-05-02 09:00:00", "250.00", "sparen", "Samen", "NL45 ABNA 0503 737143")]]}
    reports = sync_connection(db, connection, _client(FakeBunq(pages)), dry_run=False)
    db.commit()
    assert reports[0].transfers_linked == 1
    incoming = db.query(Transaction).filter_by(account_id=account.id).one()
    db.refresh(outgoing)
    assert incoming.transfer_id == outgoing.id and outgoing.transfer_id == incoming.id


def test_ambiguous_transfer_is_left_alone(db):
    user, account, connection, link = _world(db)
    abn = Account(user_id=user.id, name="ABN", bank="abn_amro", iban="NL45ABNA0503737143")
    db.add(abn)
    db.flush()
    for n in (1, 2):
        db.add(Transaction(account_id=abn.id, date=date(2026, 5, 1), amount=Decimal("-250.00"),
                           counterparty_iban="NL01BUNQ0000000001", import_hash=f"abn-{n}"))
    db.flush()
    pages = {1: [[payment(1, "2026-05-02 09:00:00", "250.00", "sparen", "Samen", "NL45ABNA0503737143")]]}
    reports = sync_connection(db, connection, _client(FakeBunq(pages)), dry_run=False)
    assert reports[0].transfers_linked == 0


def test_routes_select_accounts_preview_and_import(monkeypatch, db):
    user = User(username="bunq-route", password_hash="x")
    db.add(user)
    db.flush()
    csv_account = Account(user_id=user.id, name="Bunq Samen spaar", bank="bunq")
    db.add(csv_account)
    db.flush()
    db.add(Transaction(account_id=csv_account.id, date=date(2026, 5, 1), amount=Decimal("-10.00"),
                       counterparty="Albert Heijn", import_hash="csv-1"))
    db.commit()
    csv_id = csv_account.id
    fake = FakeBunq({1: [[payment(1, "2026-05-01 10:00:00", "-10.00", "AH", "Albert Heijn"),
                          payment(2, "2026-05-02 10:00:00", "-4.00", "Brood", "Bakker")]]})
    monkeypatch.setattr(bunq_router, "SUPER_ADMIN_USERNAME", user.username)
    monkeypatch.setattr(bunq_router, "encryption_enabled", lambda: True)
    monkeypatch.setattr(bunq_router, "BunqClient", lambda base: _client(fake))
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))

    client.post("/banking/bunq", data={"api_key": API_KEY})
    page = client.post("/banking/bunq/check")
    assert page.status_code == 200 and "NL01BUNQ0000000001" in page.text
    link = db.query(BunqAccountLink).one()

    client.post("/banking/bunq/accounts", data={
        "enable": str(link.id), f"kind_{link.id}": "savings", f"account_{link.id}": str(csv_id)})
    db.expire_all()
    assert db.get(BunqAccountLink, link.id).account_id == csv_id
    assert db.get(Account, csv_id).kind == "savings" and db.get(Account, csv_id).iban == "NL01BUNQ0000000001"

    preview = client.post("/banking/bunq/sync", data={"mode": "preview"})
    assert "er is niets opgeslagen" in preview.text
    assert db.query(Transaction).count() == 1

    done = client.post("/banking/bunq/sync", data={"mode": "import"})
    assert "Import afgerond" in done.text
    db.expire_all()
    assert db.query(Transaction).filter_by(account_id=csv_id).count() == 2  # CSV + Bakker


def test_linking_to_account_without_iban_when_iban_is_taken_does_not_crash(monkeypatch, db):
    """Twee eigen rekeningen voor hetzelfde IBAN (CSV zonder IBAN + bankkoppeling met IBAN)."""
    user = User(username="bunq-dup", password_hash="x")
    db.add(user)
    db.flush()
    with_iban = Account(user_id=user.id, name="Spaar bunq", bank="bunq", iban="NL01BUNQ0000000001")
    csv_account = Account(user_id=user.id, name="Bunq Samen spaar", bank="bunq")
    db.add_all([with_iban, csv_account])
    db.commit()
    csv_id, iban_id = csv_account.id, with_iban.id

    monkeypatch.setattr(bunq_router, "SUPER_ADMIN_USERNAME", user.username)
    monkeypatch.setattr(bunq_router, "encryption_enabled", lambda: True)
    monkeypatch.setattr(bunq_router, "BunqClient", lambda base: _client(FakeBunq({1: [[]]})))
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    client.post("/banking/bunq", data={"api_key": API_KEY})
    client.post("/banking/bunq/check")
    link = db.query(BunqAccountLink).one()

    page = client.post("/banking/bunq/accounts", data={
        "enable": str(link.id), f"kind_{link.id}": "savings", f"account_{link.id}": str(csv_id)})
    assert page.status_code == 200
    assert "samenvoegen" in page.text.lower()
    db.expire_all()
    assert db.get(BunqAccountLink, link.id).account_id == csv_id
    assert db.get(Account, csv_id).iban is None          # IBAN blijft op de andere rekening
    assert db.get(Account, iban_id).iban == "NL01BUNQ0000000001"


def test_bunq_ids_use_64_bit_columns_and_large_payment_ids_sync(db):
    """bunq-betaling-id's passen niet in 32 bits (productie: 2932017837); SQLite ziet dat niet, PostgreSQL wel."""
    from sqlalchemy import BigInteger

    columns = BunqAccountLink.__table__.c
    assert isinstance(columns.last_payment_id.type, BigInteger)
    assert isinstance(columns.bunq_account_id.type, BigInteger)

    user, account, connection, link = _world(db)
    big = 2_932_017_837
    pages = {1: [[payment(big, "2026-05-01 10:00:00", "-10.00", "AH", "Albert Heijn")]]}
    sync_connection(db, connection, _client(FakeBunq(pages)), dry_run=False)
    db.commit()
    assert db.get(BunqAccountLink, link.id).last_payment_id == big
