"""Small input validators shared between routers."""


def clean_email(raw: str | None) -> str | None:
    """Basis e-mail-validatie: strip whitespace, lowercase, verwacht één '@'
    met iets ervoor en iets erna. Geen volledige RFC-validatie — we willen
    alleen overduidelijke typos afvangen. Return None als ongeldig, "" als
    bewust leeg gelaten."""
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned:
        return ""
    if " " in cleaned or cleaned.count("@") != 1:
        return None
    local, _, domain = cleaned.partition("@")
    if not local or not domain or "." not in domain:
        return None
    return cleaned
