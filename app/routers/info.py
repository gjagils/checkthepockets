"""Info / knowledge base routes (zie `app/docs/`)."""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.info_loader import (
    DEFAULT_LANG,
    list_articles,
    load_article,
    load_categories,
    load_article_meta,
    get_category,
    normalize_lang,
)
from app.template_config import templates

router = APIRouter()


def _effective_lang(lang_query: str) -> str:
    """Part 1 van LIN-38: alleen query-param + default. Cookie komt in Part 2."""
    if lang_query:
        return normalize_lang(lang_query)
    return DEFAULT_LANG


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
    effective = _effective_lang(lang)
    categories = _visible_categories(user, effective)

    return templates.TemplateResponse(
        "info/index.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "lang": effective,
        },
    )


@router.get("/info/{category_slug}")
def info_category(
    category_slug: str,
    request: Request,
    lang: str = Query(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    effective = _effective_lang(lang)
    cat = get_category(category_slug)
    if not cat or (cat.admin_only and not getattr(user, "is_admin", False)):
        return RedirectResponse("/info", status_code=302)

    articles = list_articles(category_slug, effective)
    categories = _visible_categories(user, effective)

    return templates.TemplateResponse(
        "info/category.html",
        {
            "request": request,
            "user": user,
            "category": cat,
            "articles": articles,
            "categories": categories,
            "lang": effective,
        },
    )


@router.get("/info/{category_slug}/{slug}")
def info_article(
    category_slug: str,
    slug: str,
    request: Request,
    lang: str = Query(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    effective = _effective_lang(lang)
    cat = get_category(category_slug)
    if not cat or (cat.admin_only and not getattr(user, "is_admin", False)):
        return RedirectResponse("/info", status_code=302)

    article = load_article(category_slug, slug, effective)
    if article is None:
        return RedirectResponse(f"/info/{category_slug}", status_code=302)

    # Voor de sidebar: alle artikelen van deze categorie
    sidebar_articles = list_articles(category_slug, effective)
    categories = _visible_categories(user, effective)

    return templates.TemplateResponse(
        "info/article.html",
        {
            "request": request,
            "user": user,
            "category": cat,
            "article": article,
            "sidebar_articles": sidebar_articles,
            "categories": categories,
            "lang": effective,
        },
    )
