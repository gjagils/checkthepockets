"""ACT-57a: gekoppelde overboekingen tellen mee of niet afhankelijk van het overzicht."""
import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func

from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import Account, Category, Transaction, User
from app.transfer_scope import not_internal_transfer

D = Decimal


def _world(db):
    user = User(username="ts", email="t@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    gj = Account(user_id=user.id, name="GJ Betaal", bank="abn_amro")
    otg = Account(user_id=user.id, name="GJ - On the go", bank="bunq")
    samen = Account(user_id=user.id, name="Samen Betaal", bank="abn_amro")
    db.add_all([gj, otg, samen])
    db.flush()
    otg.group_id = gj.group_id                       # GJ Betaal + On the go = één groep
    cats = {n: Category(user_id=user.id, name=n) for n in ("Bijdrage aan gezamenlijk", "Lunch en onderweg")}
    cats["Bijdrage Gerd-Jan"] = Category(user_id=user.id, name="Bijdrage Gerd-Jan", is_income=1)
    db.add_all(cats.values())
    db.flush()
    today = datetime.date.today()

    def tx(account, n, amount, category):
        t = Transaction(account_id=account.id, date=today, amount=D(amount), import_hash=f"h{n}", category_id=category.id)
        db.add(t)
        db.flush()
        return t

    a1 = tx(gj, 1, "-50", cats["Lunch en onderweg"])          # GJ Betaal -> On the go (eigen rekening)
    b1 = tx(otg, 2, "50", cats["Lunch en onderweg"])
    a1.transfer_id, b1.transfer_id = b1.id, a1.id
    a2 = tx(gj, 3, "-100", cats["Bijdrage aan gezamenlijk"])  # GJ Betaal -> Samen Betaal (tussen personen)
    b2 = tx(samen, 4, "100", cats["Bijdrage Gerd-Jan"])
    a2.transfer_id, b2.transfer_id = b2.id, a2.id
    tx(otg, 5, "-4", cats["Lunch en onderweg"])               # gewone uitgave
    db.commit()
    return user, gj, otg, samen, cats


def _sum(db, user, account_ids, sign):
    q = db.query(func.coalesce(func.sum(Transaction.amount), 0)).join(Account, Account.id == Transaction.account_id).filter(
        Account.user_id == user.id, not_internal_transfer(account_ids))
    if account_ids:
        q = q.filter(Transaction.account_id.in_(account_ids))
    q = q.filter(Transaction.amount < 0 if sign < 0 else Transaction.amount > 0)
    return D(str(q.scalar()))


def test_all_accounts_view_drops_both_sides_of_every_pair(db):
    user, gj, otg, samen, cats = _world(db)
    assert _sum(db, user, None, -1) == D("-4") and _sum(db, user, None, +1) == D("0")
    all_ids = [gj.id, otg.id, samen.id]
    assert _sum(db, user, all_ids, -1) == D("-4") and _sum(db, user, all_ids, +1) == D("0")


def test_group_view_drops_internal_pair_but_keeps_contribution_to_the_joint_account(db):
    user, gj, otg, samen, cats = _world(db)
    gj_group = [gj.id, otg.id]
    assert _sum(db, user, gj_group, -1) == D("-104")          # -100 bijdrage + -4 lunch; -50/+50 valt weg
    assert _sum(db, user, gj_group, +1) == D("0")
    assert _sum(db, user, [samen.id], +1) == D("100")         # inkomen voor de gezamenlijke rekening
    assert _sum(db, user, [samen.id], -1) == D("0")


def test_single_account_view_keeps_transfers_to_other_accounts(db):
    user, gj, otg, samen, cats = _world(db)
    assert _sum(db, user, [gj.id], -1) == D("-150")           # beide uitgaande overboekingen: tegenboeking elders
    assert _sum(db, user, [otg.id], +1) == D("50")


def test_budget_page_group_view_counts_the_contribution_as_spending(db):
    user, gj, otg, samen, cats = _world(db)
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    assert client.get(f"/budgets?group_id={gj.group_id}").status_code == 200
    assert client.get(f"/budgets?group_id={samen.group_id}").status_code == 200
    assert client.get("/budgets").status_code == 200
    assert client.get("/analytics").status_code == 200 and client.get(f"/analytics?account_id={gj.id}").status_code == 200
