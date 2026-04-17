from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.models import Person
from app.template_config import templates

router = APIRouter(prefix="/persons")


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
        "persons/list.html",
        {"request": request, "user": user, "persons": persons},
    )


@router.post("")
def create_person(
    request: Request,
    name: str = Form(...),
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
        db.add(Person(user_id=user.id, name=clean, sort_order=max_order))
        db.commit()
    return RedirectResponse("/persons", status_code=302)


@router.post("/{person_id}/rename")
def rename_person(
    person_id: int,
    request: Request,
    name: str = Form(...),
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
        db.commit()
    return RedirectResponse("/persons", status_code=302)


@router.post("/{person_id}/delete")
def delete_person(
    person_id: int,
    request: Request,
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
    return RedirectResponse("/persons", status_code=302)


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
