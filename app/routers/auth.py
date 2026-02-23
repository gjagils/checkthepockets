from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.auth import (
    hash_password,
    verify_password,
    set_session_cookie,
    get_current_user,
    require_login,
    COOKIE_NAME,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Ongeldige gebruikersnaam of wachtwoord"},
            status_code=401,
        )
    response = RedirectResponse("/", status_code=302)
    return set_session_cookie(response, user.id)


@router.get("/register")
def register_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("auth/register.html", {"request": request})


@router.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    errors = []
    if len(username) < 3:
        errors.append("Gebruikersnaam moet minimaal 3 tekens zijn")
    if len(password) < 8:
        errors.append("Wachtwoord moet minimaal 8 tekens zijn")
    if password != password_confirm:
        errors.append("Wachtwoorden komen niet overeen")
    if db.query(User).filter(User.username == username).first():
        errors.append("Gebruikersnaam is al in gebruik")

    if errors:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "errors": errors, "username": username},
            status_code=400,
        )

    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    response = RedirectResponse("/", status_code=302)
    return set_session_cookie(response, user.id)


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    return templates.TemplateResponse(
        "auth/settings.html",
        {"request": request, "user": user},
    )


@router.post("/settings/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    errors = []
    if not verify_password(current_password, user.password_hash):
        errors.append("Huidig wachtwoord is onjuist")
    if len(new_password) < 8:
        errors.append("Nieuw wachtwoord moet minimaal 8 tekens zijn")
    if new_password != new_password_confirm:
        errors.append("Nieuwe wachtwoorden komen niet overeen")

    if errors:
        return templates.TemplateResponse(
            "auth/settings.html",
            {"request": request, "user": user, "errors": errors},
            status_code=400,
        )

    user.password_hash = hash_password(new_password)
    db.commit()

    return templates.TemplateResponse(
        "auth/settings.html",
        {"request": request, "user": user, "success": "Wachtwoord succesvol gewijzigd"},
    )


@router.post("/settings/delete-account")
def delete_account(
    request: Request,
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)

    if not verify_password(confirm_password, user.password_hash):
        return templates.TemplateResponse(
            "auth/settings.html",
            {"request": request, "user": user, "delete_error": "Wachtwoord is onjuist"},
            status_code=400,
        )

    db.delete(user)
    db.commit()

    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response
