"""Info / knowledge base routes (zie `app/docs/`)."""
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.info_loader import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    list_articles,
    load_article,
    load_categories,
    load_article_meta,
    get_category,
    normalize_lang,
)
from app.template_config import templates

router = APIRouter()

LANG_COOKIE = "info_lang"
LANG_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 jaar


def _resolve_lang(request: Request, lang_query: str) -> tuple[str, bool]:
    """Resolve taalkeuze: query > cookie > default.

    Returns (lang, was_explicit) — `was_explicit=True` betekent dat de gebruiker
    de taal expliciet heeft gekozen via query-param en we de cookie moeten zetten.
    """
    if lang_query:
        return normalize_lang(lang_query), True
    cookie = request.cookies.get(LANG_COOKIE)
    if cookie and cookie.lower() in SUPPORTED_LANGS:
        return cookie.lower(), False
    return DEFAULT_LANG, False


def _maybe_set_lang_cookie(response: Response, lang: str, was_explicit: bool) -> None:
    if was_explicit:
        response.set_cookie(
            key=LANG_COOKIE,
            value=lang,
            max_age=LANG_COOKIE_MAX_AGE,
            httponly=False,  # JS-switcher kan 'm lezen
            samesite="lax",
        )


def _visible_categories(user, lang: str):
    """Return categorieën + per categorie een voor-ingeladen article-meta lijst.

    Admin-only-categorieën blijven verborgen voor niet-admins. Het admin-flag-
    filter komt inhoudelijk aan in Part 3, maar de infrastructuur zit er nu al.
    """
    cats = []
    for cat in load_categories():
        if cat.admin_only and not getattr(user, "is_admin", False):
            continue
        cats.append(cat)
    return cats


@router.get("/info")
def info_index(
    request: Request,
    lang: str = Query(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    effective, was_explicit = _resolve_lang(request, lang)
    categories = _visible_categories(user, effective)

    response = templates.TemplateResponse(
        "info/index.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "lang": effective,
            "current_path": "/info",
        },
    )
    _maybe_set_lang_cookie(response, effective, was_explicit)
    return response


@router.get("/info/{category_slug}")
def info_category(
    category_slug: str,
    request: Request,
    lang: str = Query(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    effective, was_explicit = _resolve_lang(request, lang)
    cat = get_category(category_slug)
    if not cat or (cat.admin_only and not getattr(user, "is_admin", False)):
        return RedirectResponse("/info", status_code=302)

    articles = list_articles(category_slug, effective)
    categories = _visible_categories(user, effective)

    response = templates.TemplateResponse(
        "info/category.html",
        {
            "request": request,
            "user": user,
            "category": cat,
            "articles": articles,
            "categories": categories,
            "lang": effective,
            "current_path": f"/info/{category_slug}",
        },
    )
    _maybe_set_lang_cookie(response, effective, was_explicit)
    return response


@router.get("/info/{category_slug}/{slug}")
def info_article(
    category_slug: str,
    slug: str,
    request: Request,
    lang: str = Query(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    effective, was_explicit = _resolve_lang(request, lang)
    cat = get_category(category_slug)
    if not cat or (cat.admin_only and not getattr(user, "is_admin", False)):
        return RedirectResponse("/info", status_code=302)

    article = load_article(category_slug, slug, effective)
    if article is None:
        return RedirectResponse(f"/info/{category_slug}", status_code=302)

    # Voor de sidebar: alle artikelen van deze categorie
    sidebar_articles = list_articles(category_slug, effective)
    categories = _visible_categories(user, effective)

    response = templates.TemplateResponse(
        "info/article.html",
        {
            "request": request,
            "user": user,
            "category": cat,
            "article": article,
            "sidebar_articles": sidebar_articles,
            "categories": categories,
            "lang": effective,
            "current_path": f"/info/{category_slug}/{slug}",
        },
    )
    _maybe_set_lang_cookie(response, effective, was_explicit)
    return response
