"""ACT-57b: overboekingen koppelen en categoriseren op soort."""
import datetime
from decimal import Decimal

from app.auth import hash_password
from app.models import Account, Category, Person, Transaction, User
from app.transfer_service import link_and_classify, plan_pairs

D = Decimal
GJ_IBAN, OTG_IBAN, SAMEN_IBAN, SPAAR_IBAN = "NL01GJ0000000001", "NL02OTG000000002", "NL03SAMEN0000003", "NL04SPAAR0000004"


def _world(db):
    user = User(username="tsv", email="t@example.test", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    gerd = Person(user_id=user.id, name="Gerd-Jan")
    nelleke = Person(user_id=user.id, name="Nelleke")
    samen = Person(user_id=user.id, name="Nelleke/Gerd-Jan")
    db.add_all([gerd, nelleke, samen])
    db.flush()
    gj = Account(user_id=user.id, name="GJ Betaal", bank="abn_amro", iban=GJ_IBAN)
    otg = Account(user_id=user.id, name="GJ - On the go", bank="bunq", iban=OTG_IBAN)
    joint = Account(user_id=user.id, name="Samen Betaal", bank="abn_amro", iban=SAMEN_IBAN)
    spaar = Account(user_id=user.id, name="GJ - Spaar", bank="bunq", iban=SPAAR_IBAN, kind="savings")
    db.add_all([gj, otg, joint, spaar])
    db.flush()
    gj.owners, otg.owners, joint.owners, spaar.owners = [gerd], [gerd], [samen], [gerd]
    otg.group_id = gj.group_id
    cats = {}
    for hoofd, subs in (("Overboekingen", ["Eigen rekeningen"]), ("Financieel", ["Bijdrage aan gezamenlijk"]),
                        ("Inkomen", ["Bijdrage Gerd-Jan", "Bijdrage Nelleke"])):
        parent = Category(user_id=user.id, name=hoofd)
        db.add(parent)
        db.flush()
        for sub in subs:
            c = Category(user_id=user.id, name=sub, parent_id=parent.id)
            db.add(c)
            cats[sub] = c
    db.flush()
    return user, {"gj": gj, "otg": otg, "samen": samen, "spaar": spaar}, cats


def _tx(db, account, n, amount, counterparty_iban, day=0, category=None):
    t = Transaction(account_id=account.id, date=datetime.date(2026, 10, 1) + datetime.timedelta(days=day),
                    amount=D(amount), counterparty_iban=counterparty_iban, import_hash=f"h{n}",
                    category_id=category.id if category else None)
    db.add(t)
    db.flush()
    return t


def test_own_account_transfer_is_linked_and_both_sides_get_eigen_rekeningen(db):
    user, acc, cats = _world(db)
    a = _tx(db, acc["gj"], 1, "-50", OTG_IBAN)
    b = _tx(db, acc["otg"], 2, "50", GJ_IBAN, day=1)
    result = link_and_classify(db, user.id, since_days=None)
    assert (result.linked, result.categorized) == (1, 2)
    assert a.transfer_id == b.id and b.transfer_id == a.id
    assert a.category_id == b.category_id == cats["Eigen rekeningen"].id


def test_contribution_to_the_joint_account_gets_contribution_categories(db):
    user, acc, cats = _world(db)
    a = _tx(db, acc["gj"], 1, "-2400", SAMEN_IBAN)
    b = _tx(db, acc["samen"], 2, "2400", GJ_IBAN, day=2)
    pairs = plan_pairs(db, user.id)
    assert [p.kind for p in pairs] == ["persons"]
    link_and_classify(db, user.id, since_days=None)
    assert a.category_id == cats["Bijdrage aan gezamenlijk"].id
    assert b.category_id == cats["Bijdrage Gerd-Jan"].id


def test_existing_category_is_kept_and_savings_transfers_keep_their_own_category(db):
    user, acc, cats = _world(db)
    keep = Category(user_id=user.id, name="Eigen keuze")
    db.add(keep)
    db.flush()
    a = _tx(db, acc["gj"], 1, "-50", OTG_IBAN, category=keep)
    b = _tx(db, acc["otg"], 2, "50", GJ_IBAN)
    s1 = _tx(db, acc["gj"], 3, "-200", SPAAR_IBAN, day=10)
    s2 = _tx(db, acc["spaar"], 4, "200", GJ_IBAN, day=10)
    link_and_classify(db, user.id, since_days=None)
    assert a.category_id == keep.id and b.category_id == cats["Eigen rekeningen"].id
    assert s1.transfer_id == s2.id and s1.category_id is None and s2.category_id is None   # gekoppeld, categorie blijft


def test_ambiguous_candidates_are_not_linked_and_second_run_is_idempotent(db):
    user, acc, cats = _world(db)
    _tx(db, acc["gj"], 1, "-50", OTG_IBAN)
    _tx(db, acc["otg"], 2, "50", GJ_IBAN, day=1)
    _tx(db, acc["otg"], 3, "50", GJ_IBAN, day=2)                # twee kandidaten
    assert link_and_classify(db, user.id, since_days=None).linked == 0
    only = _tx(db, acc["gj"], 4, "-70", OTG_IBAN, day=20)
    _tx(db, acc["otg"], 5, "70", GJ_IBAN, day=20)
    assert link_and_classify(db, user.id, since_days=None).linked == 1
    assert link_and_classify(db, user.id, since_days=None).linked == 0 and only.transfer_id is not None
