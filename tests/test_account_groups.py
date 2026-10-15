"""ACT-55a: rekeninggroepen."""
from fastapi.testclient import TestClient

from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import Account, AccountGroup, User


def _setup(db):
    user = User(username="grp", email="g@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    gj = Account(user_id=user.id, name="GJ", bank="abn_amro", iban="NL91ABNA0417164300")
    otg = Account(user_id=user.id, name="On the go", bank="bunq", iban="NL81BUNQ2088619097")
    db.add_all([gj, otg])
    db.commit()
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    return user, gj, otg, client


def test_new_account_gets_its_own_group(db):
    user, gj, otg, _ = _setup(db)
    assert gj.group_id is not None and otg.group_id is not None and gj.group_id != otg.group_id
    assert gj.group.name == "GJ"


def test_group_accounts_together_and_apart_and_empty_groups_disappear(db):
    user, gj, otg, client = _setup(db)
    old_group = otg.group_id
    assert client.post(f"/accounts/{otg.id}/group", data={"group_id": str(gj.group_id)}).status_code == 200
    db.expire_all()
    assert db.get(Account, otg.id).group_id == db.get(Account, gj.id).group_id
    assert db.get(AccountGroup, old_group) is None            # lege groep opgeruimd
    page = client.get("/accounts").text
    assert "GJ (GJ + On the go)" in page or "GJ + On the go" in page
    client.post(f"/accounts/groups/{gj.group_id}/rename", data={"name": "Betaal GJ"})
    db.expire_all()
    assert db.get(Account, gj.id).group.name == "Betaal GJ"
    # weer los
    client.post(f"/accounts/{otg.id}/group", data={"group_id": ""})
    db.expire_all()
    assert db.get(Account, otg.id).group_id != db.get(Account, gj.id).group_id


def test_cannot_use_another_users_group(db):
    user, gj, otg, client = _setup(db)
    other = User(username="o", email="o@example.test", password_hash=hash_password("pw"))
    db.add(other)
    db.flush()
    foreign = Account(user_id=other.id, name="Vreemd", bank="bunq")
    db.add(foreign)
    db.commit()
    client.post(f"/accounts/{gj.id}/group", data={"group_id": str(foreign.group_id)})
    db.expire_all()
    assert db.get(Account, gj.id).group_id != foreign.group_id
