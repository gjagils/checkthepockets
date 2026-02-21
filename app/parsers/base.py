import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class ParsedTransaction:
    date: date
    amount: Decimal
    currency: str
    description: str
    counterparty: str | None = None
    counterparty_iban: str | None = None
    balance_after: Decimal | None = None

    @property
    def import_hash(self) -> str:
        raw = f"{self.date}|{self.amount}|{self.description}|{self.counterparty or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()


class ParseError(Exception):
    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(message)
