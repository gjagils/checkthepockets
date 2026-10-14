"""ACT-45a: de na-import-reeks, categorieën van terugkerende posten en de custom-CSV-parser op één plek."""
from datetime import date
from decimal import Decimal

from app import recurring_service
from app.models import Account, Category, RecurringTransaction, Transaction, User
from app.parsers.custom_csv import CUSTOM_CSV_FIELDS, csv_headers_and_preview, parse_custom_csv
from app.recurring_service import apply_item_categories, resync_after_import


def test_custom_csv_handles_european_and_us_amounts_and_skips_bad_rows():
    csv_bytes = (
        "Datum;Bedrag;Omschrijving;Tegenpartij;Categorie\n"
        "01-05-2026;1.234,56;Salaris;Werkgever;Inkomen\n"
        "2026-05-02;-12,5;Koffie;Bar;\n"
        "03/05/2026;1,234.50;Terug;Shop;\n"
        "geen datum;5;x;y;\n"
        "04-05-2026;abc;x;y;\n"
    ).encode()
    # csv.DictReader met puntkomma-scheiding: gebruik komma-gescheiden zoals de importer verwacht
    csv_bytes = csv_bytes.replace(b";", b",").replace(b"1.234,56", b'"1.234,56"').replace(b"-12,5", b'"-12,5"')
    csv_bytes = csv_bytes.replace(b"1,234.50", b'"1,234.50"')
    mapping = {"date": "Datum", "amount": "Bedrag", "description": "Omschrijving",
               "counterparty": "Tegenpartij", "category": "Categorie"}
    parsed = parse_custom_csv(csv_bytes, mapping)
    assert [(p.date, p.amount) for p in parsed] == [
        (date(2026, 5, 1), Decimal("1234.56")),
        (date(2026, 5, 2), Decimal("-12.5")),
        (date(2026, 5, 3), Decimal("1234.50")),
    ]
    assert parsed[0]._category_name == "Inkomen" and parsed[0].currency == "EUR"
    headers, preview = csv_headers_and_preview(csv_bytes)
    assert headers[0] == "Datum" and len(preview) == 5
    assert ("date", "Datum *") in CUSTOM_CSV_FIELDS


def test_resync_after_import_crosses_the_year_boundary(monkeypatch):
    calls = []
    monkeypatch.setattr(recurring_service, "auto_link_recurring_after_import", lambda db, uid: calls.append("link"))
    monkeypatch.setattr(recurring_service, "cleanup_matched_projected", lambda uid, db: calls.append("cleanup"))
    monkeypatch.setattr(recurring_service, "sync_projected_transactions",
                        lambda uid, y, m, db: calls.append((y, m)))
    monkeypatch.setattr(recurring_service.clock, "today_nl", lambda: date(2026, 11, 15))
    resync_after_import(None, 1, months_ahead=3)
    assert calls == ["link", "cleanup", (2026, 11), (2026, 12), (2027, 1)]
    calls.clear()
    resync_after_import(None, 1)
    assert calls == ["link", "cleanup", (2026, 11)]


def test_apply_item_categories_fills_only_uncategorised_linked_real_transactions(db):
    user = User(username="rec-user", password_hash="x")
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="A", bank="x")
    db.add(account)
    db.flush()
    cat_a, cat_b = Category(user_id=user.id, name="A"), Category(user_id=user.id, name="B")
    other = Category(user_id=user.id, name="Al gezet")
    db.add_all([cat_a, cat_b, other])
    db.flush()
    item_a = RecurringTransaction(user_id=user.id, name="a", amount_expected=Decimal("-1"), frequency="monthly",
                                  category_id=cat_a.id)
    item_b = RecurringTransaction(user_id=user.id, name="b", amount_expected=Decimal("-1"), frequency="monthly",
                                  category_id=cat_b.id)
    item_none = RecurringTransaction(user_id=user.id, name="zonder", amount_expected=Decimal("-1"), frequency="monthly")
    db.add_all([item_a, item_b, item_none])
    db.flush()

    def tx(n, item, **extra):
        return Transaction(account_id=account.id, date=date(2026, 5, 1), amount=Decimal("-1"), description="x",
                           import_hash=f"h{n}", recurring_id=item.id, **extra)

    db.add_all([tx(1, item_a), tx(2, item_b), tx(3, item_a, category_id=other.id), tx(4, item_a, is_projected=1),
                tx(5, item_none)])
    db.commit()
    assert apply_item_categories(db, user.id, [item_a, item_b, item_none]) == 2
    db.commit()
    got = {t.import_hash: (t.category_id, t.is_reviewed) for t in db.query(Transaction)}
    assert got["h1"] == (cat_a.id, 1) and got["h2"] == (cat_b.id, 1)
    assert got["h3"][0] == other.id and got["h4"][0] is None and got["h5"][0] is None
    assert apply_item_categories(db, user.id, []) == 0
