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


def clean_iban(raw: str | None) -> str | None:
    """Normaliseert een IBAN (spaties weg, hoofdletters) en controleert lengte en controlecijfers (mod 97).
    Geeft ``None`` terug bij een ongeldige IBAN en ``""`` bij een lege invoer."""
    if raw is None:
        return None
    iban = "".join(raw.split()).upper()
    if not iban:
        return ""
    if not (15 <= len(iban) <= 34) or not iban[:2].isalpha() or not iban[2:4].isdigit() or not iban.isalnum():
        return None
    rearranged = iban[4:] + iban[:4]
    number = "".join(str(int(ch, 36)) for ch in rearranged)
    return iban if int(number) % 97 == 1 else None
