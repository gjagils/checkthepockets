"""ACT-35: bankdata en categorienamen mogen nooit als HTML of script in pagina's terechtkomen (B4, B5)."""
import pathlib
import re
from decimal import Decimal



from fastapi.testclient import TestClient

from app import clock
from app.auth import create_session_cookie, hash_password
from app.main import app
from app.models import Account, Category, Transaction, User

PAYLOAD = "</script><script>alert('xss')</script>"


def _client(user):
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("session", create_session_cookie(user.id))
    return client


def test_dashboard_category_names_cannot_break_out_of_the_script_block(db):
    today = clock.today_nl()
    user = User(username="xss-user", password_hash=hash_password("x" * 10))
    db.add(user)
    db.flush()
    account = Account(user_id=user.id, name="Betaal", bank="abn_amro")
    db.add(account)
    db.flush()
    parent = Category(user_id=user.id, name=PAYLOAD)
    db.add(parent)
    db.flush()
    db.add(Transaction(account_id=account.id, date=today, amount=Decimal("-10.00"), category_id=parent.id,
                       description="x", import_hash="h1"))
    db.commit()

    for query in (f"?year={today.year}", f"?year={today.year}&month={today.month}",
                  f"?year={today.year}&month={today.month}&category_id={parent.id}"):
        page = _client(user).get("/dashboard" + query)
        assert page.status_code == 200, query
        assert PAYLOAD not in page.text, query
        assert "<script>alert('xss')" not in page.text, query


def test_savings_match_list_builds_rows_with_textcontent():
    source = pathlib.Path("app/templates/savings/detail.html").read_text()
    start = source.index("(data.items || []).forEach(function (tx)")
    block = source[start:source.index("list.appendChild(row);", start)]
    assert "textContent" in block
    assert "tx.label" in block and "innerHTML" not in block         # geen innerHTML met bankdata


def test_no_unescaped_json_or_jinja_strings_in_script_literals():
    """Geen `| safe` op data en geen Jinja-waarde tussen quotes in JS: gebruik `| tojson`."""
    offenders = []
    for path in pathlib.Path("app/templates").rglob("*.html"):
        text = path.read_text()
        for number, line in enumerate(text.splitlines(), 1):
            line = re.sub(r"\{\{\s*[\w.]*\.id\s*\}\}", "ID", line)   # integer ids in URL paths are safe
            if re.search(r"\|\s*safe", line) and "article.html" not in str(path):
                offenders.append(f"{path}:{number} safe")
            if re.search(r"""=\s*['"]\{\{[^}|]*\}\}['"]\s*;""", line) or re.search(r"""\(\s*'[^']*\{\{[^}|]+\}\}""", line):
                if "<script" in line or "formData" in line or "append(" in line or "fetch(" in line or "confirm(" in line:
                    offenders.append(f"{path}:{number} jinja-in-js")
    assert offenders == []


def test_every_template_still_compiles():
    from app.template_config import templates
    for path in pathlib.Path("app/templates").rglob("*.html"):
        templates.env.get_template(str(path.relative_to("app/templates")))


def test_username_cannot_break_out_of_an_inline_confirm(db):
    """Stored XSS: een gebruikersnaam eindigend op `');alert(1);//` draaide uit bij de beheerder."""
    admin = User(username="beheerder", password_hash=hash_password("x" * 10), is_admin=1)
    evil = User(username="x');alert(1);//", password_hash=hash_password("x" * 10))
    db.add_all([admin, evil])
    db.commit()
    page = _client(admin).get("/admin/users")
    assert page.status_code == 200
    assert "');alert(1)" not in page.text and '");alert(1)' not in page.text
    assert "\\u0027);alert(1)" in page.text            # als JSON-string in het attribuut, quote ontsnapt
