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
                        ("Inkomen", ["Bijdrage Gerd-Jan", "Bijdrage Nelleke"]),
                        ("Sparen", ["Storting Gerd-Jan", "Storting Nelleke", "Storting samen"]),
                        ("Kinderen", ["Hannah"])):
        parent = Category(user_id=user.id, name=hoofd)
        db.add(parent)
        db.flush()
        for sub in subs:
            c = Category(user_id=user.id, name=sub, parent_id=parent.id)
            db.add(c)
            cats[sub] = c
    db.flush()
    return user, {"gj": gj, "otg": otg, "samen": joint, "spaar": spaar}, cats


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
    assert s1.transfer_id == s2.id and s1.category_id is None and s2.category_id is None   # eenmalig: alleen koppelen


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


def test_repair_page_previews_then_applies_and_reports_unmatched_contributions(db):
    from fastapi.testclient import TestClient

    from app.auth import create_session_cookie
    from app.main import app

    user, acc, cats = _world(db)
    own_a = _tx(db, acc["gj"], 1, "-50", OTG_IBAN)
    own_b = _tx(db, acc["otg"], 2, "50", GJ_IBAN, day=1)
    sender = _tx(db, acc["gj"], 3, "-2400", SAMEN_IBAN, day=5)
    receiver = _tx(db, acc["samen"], 4, "2400", GJ_IBAN, day=5)
    lonely = _tx(db, acc["samen"], 5, "9900", None, day=9, category=cats["Bijdrage Nelleke"])   # geen tegenboeking
    db.commit()
    client = TestClient(app)
    client.cookies.set("session", create_session_cookie(user.id))
    page = client.get("/accounts/transfers").text
    assert "eigen rekening" in page and "tussen personen" in page and "Bijdragen zonder tegenboeking" in page
    assert "Bijdrage Nelleke: 1" in page
    db.expire_all()
    assert db.get(Transaction, own_a.id).transfer_id is None                # preview schrijft niets
    res = client.post("/accounts/transfers")
    assert res.status_code == 200 and "overboekingen gekoppeld" in res.text
    db.expire_all()
    assert db.get(Transaction, own_a.id).transfer_id == own_b.id
    assert db.get(Transaction, sender.id).category_id == cats["Bijdrage aan gezamenlijk"].id
    assert db.get(Transaction, receiver.id).category_id == cats["Bijdrage Gerd-Jan"].id
    assert db.get(Transaction, lonely.id).transfer_id is None
    assert "geen overeenkomende overboekingen" in client.get("/accounts/transfers").text


def test_iban_in_the_description_is_used_when_the_counterparty_field_is_empty(db):
    user, acc, cats = _world(db)
    a = _tx(db, acc["gj"], 1, "-25", None)
    a.description = f"SEPA Periodieke overb. IBAN: {SPAAR_IBAN} BIC: BUNQNL2A Naam: Hannah"
    b = _tx(db, acc["spaar"], 2, "25", None, day=1)
    b.description = f"SEPA Periodieke overb. IBAN: {GJ_IBAN} BIC: ABNANL2A Naam: GJA VAN GILS"
    db.flush()
    assert link_and_classify(db, user.id, since_days=None).linked == 1
    assert a.transfer_id == b.id and b.transfer_id == a.id


# ── ACT-59: vaste spaarstortingen ─────────────────────────────────────────────

def _monthly(db, sender, receiver, amount, months, start=0, n0=100):
    """Een storting per maand van `sender` naar `receiver`; geeft de paren (afzender, ontvanger) terug."""
    out = []
    for i in range(months):
        day = start + 30 * i
        s = _tx(db, sender, n0 + 2 * i, f"-{amount}", receiver.iban, day=day)
        r = _tx(db, receiver, n0 + 2 * i + 1, amount, sender.iban, day=day)
        out.append((s, r))
    return out


def test_monthly_savings_deposit_gets_storting_on_both_sides(db):
    user, acc, cats = _world(db)
    pairs = _monthly(db, acc["gj"], acc["spaar"], "400", 3)
    result = link_and_classify(db, user.id, since_days=None)
    assert result.linked == 3 and result.categorized == 6
    for s, r in pairs:
        assert s.category_id == r.category_id == cats["Storting Gerd-Jan"].id


def test_deposit_from_the_joint_account_is_storting_samen_and_to_a_child_is_kinderen(db):
    user, acc, cats = _world(db)
    samen_person = acc["samen"].owners[0]
    joint_spaar = Account(user_id=user.id, name="Samen Spaar Bunq", bank="bunq", iban="NL05SAMSP0000005",
                          kind="savings")
    hannah = Person(user_id=user.id, name="Hannah")
    db.add_all([joint_spaar, hannah])
    db.flush()
    kid = Account(user_id=user.id, name="Hannah KinderSpaar", bank="abn_amro", iban="NL06HANNA0000006", kind="savings")
    db.add(kid)
    db.flush()
    joint_spaar.owners, kid.owners = [samen_person], [hannah]
    joint = _monthly(db, acc["samen"], joint_spaar, "200", 3, n0=200)
    mine = _monthly(db, acc["gj"], joint_spaar, "100", 3, n0=300)
    child = _monthly(db, acc["gj"], kid, "25", 3, n0=400)
    link_and_classify(db, user.id, since_days=None)
    assert {s.category_id for s, r in joint} == {cats["Storting samen"].id}
    assert {r.category_id for s, r in mine} == {cats["Storting Gerd-Jan"].id}
    assert {r.category_id for s, r in child} == {cats["Hannah"].id}


def test_withdrawals_and_incidental_or_irregular_amounts_are_only_linked(db):
    user, acc, cats = _world(db)
    back = [(_tx(db, acc["spaar"], 10 + 2 * i, "-750", GJ_IBAN, day=30 * i),
             _tx(db, acc["gj"], 11 + 2 * i, "750", SPAAR_IBAN, day=30 * i)) for i in range(3)]   # terugboeking
    once = (_tx(db, acc["gj"], 50, "-1500", SPAAR_IBAN, day=5), _tx(db, acc["spaar"], 51, "1500", GJ_IBAN, day=5))
    sparse = [(_tx(db, acc["gj"], 60 + 2 * i, "-500", SPAAR_IBAN, day=180 * i),
               _tx(db, acc["spaar"], 61 + 2 * i, "500", GJ_IBAN, day=180 * i)) for i in range(3)]  # halfjaarlijks
    link_and_classify(db, user.id, since_days=None)
    for s, r in back + [once] + sparse:
        assert s.transfer_id == r.id
        assert s.category_id is None and r.category_id is None


def test_regularity_uses_full_history_and_already_linked_pairs_are_filled(db):
    """Bunq koppelt alleen; de volgende import vult dan alsnog de categorie, ook buiten het importvenster."""
    user, acc, cats = _world(db)
    pairs = _monthly(db, acc["gj"], acc["spaar"], "400", 4)
    for s, r in pairs:                       # gekoppeld zonder categorie, zoals na de bunq-sync
        s.transfer_id, r.transfer_id = r.id, s.id
    db.flush()
    preview = plan_pairs(db, user.id, since_days=None, include_linked=True)
    assert [p.kind for p in preview] == ["savings"] * 4 and all(p.linked for p in preview)
    assert all(s.category_id is None for s, r in pairs)        # plannen schrijft niets
    result = link_and_classify(db, user.id, since_days=None)
    assert (result.linked, result.categorized) == (0, 8)
    assert {s.category_id for s, r in pairs} == {cats["Storting Gerd-Jan"].id}


def test_has_monthly_run_needs_three_roughly_monthly_dates_in_a_row():
    from app.transfer_service import has_monthly_run

    d = datetime.date
    assert has_monthly_run([d(2026, 1, 1), d(2026, 2, 1), d(2026, 3, 2)])
    assert not has_monthly_run([d(2026, 1, 1), d(2026, 2, 1)])
    assert not has_monthly_run([d(2026, 1, 1), d(2026, 1, 8), d(2026, 1, 15)])        # wekelijks: geen maandritme
    assert not has_monthly_run([d(2025, 1, 1), d(2025, 7, 1), d(2026, 1, 1)])
