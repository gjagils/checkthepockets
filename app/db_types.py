"""Eigen kolomtypes."""
from sqlalchemy import Integer
from sqlalchemy.types import TypeDecorator


class Flag(TypeDecorator):
    """Ja/nee-vlag die in de database een integer (0/1) blijft en in Python een ``bool`` is (ACT-52).

    Bestaande queries als ``User.is_admin == 1`` en toewijzingen als ``user.is_admin = 1`` blijven werken:
    de waarde wordt bij het opslaan naar 0/1 omgezet. Vergelijk in nieuwe code liever zonder ``== 1``
    (``User.is_admin.is_(True)`` of ``filter(User.is_admin)`` werkt op PostgreSQL pas na de echte
    Boolean-migratie; tot die tijd ``== 1`` blijven gebruiken in SQL-filters).
    """

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return 1 if value.strip().lower() in ("1", "true", "t", "yes", "ja", "on") else 0
        return 1 if value else 0

    def process_result_value(self, value, dialect):
        return None if value is None else bool(value)
