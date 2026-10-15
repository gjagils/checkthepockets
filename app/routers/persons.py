import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.models import Person
from app.person_forecast import build_person_forecast
from app.person_utils import format_age_nl
from app.redirects import safe_redirect
from app.template_config import templates

router = APIRouter(prefix="/persons")


def _parse_birthdate(raw: str) -> datetime.date | None:
    """HTML `<input type="date">` levert ISO-formaat; lege input = None."""
    clean = (raw or "").strip()
    if not clean:
        return None
    try:
        return datetime.date.fromisoformat(clean)
    except ValueError:
        return None


@router.get("")
def list_persons(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    persons = (
        db.query(Person)
        .filter(Person.user_id == user.id)
        .order_by(Person.sort_order, Person.name)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "persons/list.html",
        {
            "request": request,
            "user": user,
            "persons": persons,
            "format_age_nl": format_age_nl,
        },
    )


PERIODS = [(3, "3 mnd"), (6, "6 mnd"), (12, "12 mnd"), (24, "2 jaar"), (36, "3 jaar"), (60, "5 jaar")]


@router.get("/verwachting")
def first_person_forecast(request: Request, period: int = Query(12), db: Session = Depends(get_db)):
    """Menu-ingang: de verwachting van de eerste persoon in de ingestelde volgorde."""
    user = require_login(request, db)
    first = (
        db.query(Person).filter(Person.user_id == user.id)
        .order_by(Person.sort_order, Person.name).first()
    )
    if first is None:
        return RedirectResponse("/persons", status_code=302)
    return RedirectResponse(f"/persons/{first.id}?period={period}", status_code=302)


@router.get("/{person_id}")
def person_page(request: Request, person_id: int, period: int = Query(12), db: Session = Depends(get_db)):
    """Verwachting per persoon: betaalrekeningen en vermogen (ACT-53)."""
    user = require_login(request, db)
    months = period if period in {p for p, _ in PERIODS} else 12
    forecast = build_person_forecast(db, user.id, person_id, months)
    if forecast is None:
        raise HTTPException(status_code=404, detail="Persoon niet gevonden")
    persons = (
        db.query(Person).filter(Person.user_id == user.id)
        .order_by(Person.sort_order, Person.name).all()
    )
    rows = forecast["rows"]
    chart = {
        "labels": [r["month"].strftime("%m-%Y") for r in rows],
        "balance": [float(r["balance"]) for r in rows],
        "wealth": [float(r["wealth"]["total"]) for r in rows],
    }
    return templates.TemplateResponse(
        request,
        "persons/detail.html",
        {
            "request": request, "user": user, "persons": persons, "forecast": forecast,
            "person": forecast["person"], "period": months, "periods": PERIODS, "chart": chart,
        },
    )


@router.post("")
def create_person(
    request: Request,
    name: str = Form(...),
    birthdate: str = Form(""),
    redirect_to: str = Form("/persons"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    clean = name.strip()
    if clean:
        # Achter bestaande personen plaatsen
        max_order = (
            db.query(Person)
            .filter(Person.user_id == user.id)
            .count()
        )
        db.add(Person(
            user_id=user.id,
            name=clean,
            birthdate=_parse_birthdate(birthdate),
            sort_order=max_order,
        ))
        db.commit()
    return safe_redirect(redirect_to, "/persons")


@router.post("/{person_id}/rename")
def rename_person(
    person_id: int,
    request: Request,
    name: str = Form(...),
    birthdate: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    person = (
        db.query(Person)
        .filter(Person.id == person_id, Person.user_id == user.id)
        .first()
    )
    clean = name.strip()
    if person and clean:
        person.name = clean
        person.birthdate = _parse_birthdate(birthdate)
        db.commit()
    return RedirectResponse("/persons", status_code=302)


@router.post("/{person_id}/delete")
def delete_person(
    person_id: int,
    request: Request,
    redirect_to: str = Form("/persons"),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    person = (
        db.query(Person)
        .filter(Person.id == person_id, Person.user_id == user.id)
        .first()
    )
    if person:
        db.delete(person)
        db.commit()
    return safe_redirect(redirect_to, "/persons")


def _swap(a: Person, b: Person) -> None:
    a.sort_order, b.sort_order = b.sort_order, a.sort_order


@router.post("/{person_id}/move")
def move_person(
    person_id: int,
    request: Request,
    direction: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    persons = (
        db.query(Person)
        .filter(Person.user_id == user.id)
        .order_by(Person.sort_order, Person.name)
        .all()
    )
    # Normaliseer sort_order (bijv. als alle waarden 0 zijn)
    for idx, p in enumerate(persons):
        p.sort_order = idx

    idx = next((i for i, p in enumerate(persons) if p.id == person_id), None)
    if idx is None:
        return RedirectResponse("/persons", status_code=302)

    if direction == "up" and idx > 0:
        _swap(persons[idx - 1], persons[idx])
    elif direction == "down" and idx < len(persons) - 1:
        _swap(persons[idx], persons[idx + 1])

    db.commit()
    return RedirectResponse("/persons", status_code=302)
