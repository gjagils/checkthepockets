"""Loader voor de knowledge base (`app/docs/`).

Leest `manifest.yml` en de bijbehorende markdown-files per taal. Artikelen
worden on-demand gerenderd naar HTML via Python-Markdown; er wordt geen cache
aangelegd (content is klein, render-tijd verwaarloosbaar).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import frontmatter
import markdown as md
import yaml

DOCS_DIR = Path(__file__).resolve().parent / "docs"
MANIFEST_PATH = DOCS_DIR / "manifest.yml"
SUPPORTED_LANGS = ("nl", "en")
DEFAULT_LANG = "nl"

MD_EXTENSIONS = ["fenced_code", "tables", "toc", "attr_list"]


@dataclass
class Category:
    slug: str
    title_nl: str
    title_en: str
    icon: str
    order: int
    admin_only: bool = False

    def title(self, lang: str) -> str:
        return self.title_en if lang == "en" else self.title_nl


@dataclass
class ArticleMeta:
    slug: str
    title: str
    summary: str
    order: int
    updated: str
    lang: str  # taal waarin het artikel daadwerkelijk is geladen (kan fallback zijn)
    requested_lang: str  # taal die de gebruiker opvroeg


@dataclass
class Article:
    meta: ArticleMeta
    html: str


def normalize_lang(lang: Optional[str]) -> str:
    if lang and lang.lower() in SUPPORTED_LANGS:
        return lang.lower()
    return DEFAULT_LANG


def load_categories() -> list[Category]:
    if not MANIFEST_PATH.exists():
        return []
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("categories", []) or []
    cats: list[Category] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("slug"):
            continue
        cats.append(
            Category(
                slug=str(item["slug"]),
                title_nl=str(item.get("title_nl", item["slug"])),
                title_en=str(item.get("title_en", item["slug"])),
                icon=str(item.get("icon", "📄")),
                order=int(item.get("order", 999)),
                admin_only=bool(item.get("admin_only", False)),
            )
        )
    cats.sort(key=lambda c: (c.order, c.slug))
    return cats


def get_category(slug: str) -> Optional[Category]:
    for cat in load_categories():
        if cat.slug == slug:
            return cat
    return None


def _article_path(category_slug: str, slug: str, lang: str) -> Path:
    return DOCS_DIR / category_slug / f"{slug}.{lang}.md"


def _load_raw(path: Path) -> Optional[frontmatter.Post]:
    if not path.exists():
        return None
    try:
        return frontmatter.load(path)
    except Exception:
        return None


def list_articles(category_slug: str, lang: str) -> list[ArticleMeta]:
    """Lijst alle artikelen in een categorie voor de gevraagde taal.

    Als een artikel niet in de gevraagde taal bestaat wordt het alternatief
    (andere taal) gebruikt als fallback zodat de sidebar compleet blijft.
    """
    lang = normalize_lang(lang)
    other = "en" if lang == "nl" else "nl"
    cat_dir = DOCS_DIR / category_slug
    if not cat_dir.is_dir():
        return []

    seen_slugs: set[str] = set()
    for path in cat_dir.glob(f"*.{lang}.md"):
        seen_slugs.add(path.name.rsplit(".", 2)[0])
    for path in cat_dir.glob(f"*.{other}.md"):
        seen_slugs.add(path.name.rsplit(".", 2)[0])

    result: list[ArticleMeta] = []
    for slug in sorted(seen_slugs):
        meta = load_article_meta(category_slug, slug, lang)
        if meta:
            result.append(meta)
    result.sort(key=lambda m: (m.order, m.slug))
    return result


def load_article_meta(category_slug: str, slug: str, lang: str) -> Optional[ArticleMeta]:
    lang = normalize_lang(lang)
    other = "en" if lang == "nl" else "nl"
    post = _load_raw(_article_path(category_slug, slug, lang))
    actual_lang = lang
    if post is None:
        post = _load_raw(_article_path(category_slug, slug, other))
        actual_lang = other
    if post is None:
        return None
    fm = post.metadata or {}
    return ArticleMeta(
        slug=slug,
        title=str(fm.get("title", slug)),
        summary=str(fm.get("summary", "")),
        order=int(fm.get("order", 999)),
        updated=str(fm.get("updated", "")),
        lang=actual_lang,
        requested_lang=lang,
    )


def load_article(category_slug: str, slug: str, lang: str) -> Optional[Article]:
    lang = normalize_lang(lang)
    other = "en" if lang == "nl" else "nl"
    post = _load_raw(_article_path(category_slug, slug, lang))
    actual_lang = lang
    if post is None:
        post = _load_raw(_article_path(category_slug, slug, other))
        actual_lang = other
    if post is None:
        return None

    fm = post.metadata or {}
    html = md.markdown(post.content, extensions=MD_EXTENSIONS)
    meta = ArticleMeta(
        slug=slug,
        title=str(fm.get("title", slug)),
        summary=str(fm.get("summary", "")),
        order=int(fm.get("order", 999)),
        updated=str(fm.get("updated", "")),
        lang=actual_lang,
        requested_lang=lang,
    )
    return Article(meta=meta, html=html)
