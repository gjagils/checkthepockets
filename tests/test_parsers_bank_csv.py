"""ING- en Rabobank-CSV: nog nergens getest (ACT-51)."""
from datetime import date
from decimal import Decimal

import pytest

from app.parsers import ing, rabobank
from app.parsers.base import ParseError

ING_CSV = (
    '"Datum";"Naam / Omschrijving";"Rekening";"Tegenrekening";"Code";"Af Bij";"Bedrag (EUR)";"Mutatiesoort";"Mededelingen"\n'
    '"20260503";"Albert Heijn 1234";"NL91INGB0001234567";"";"BA";"Af";"12,34";"Betaalautomaat";"Pasvolgnr: 001 03-05-2026"\n'
    '"20260501";"Werkgever BV";"NL91INGB0001234567";"NL02ABNA0123456789";"OV";"Bij";"2.500,00";"Overschrijving";"Salaris april"\n'
)

RABO_CSV = (
    '"IBAN/BBAN","Munt","BIC","Volgnr","Datum","Rentedatum","Bedrag","Saldo na trn","Tegenrekening IBAN/BBAN",'
    '"Naam tegenpartij","Omschrijving-1","Omschrijving-2","Omschrijving-3"\n'
    '"NL91RABO0123456789","EUR","RABONL2U","1","2026-05-03","2026-05-03","-12,34","987,66","NL02ABNA0123456789",'
    '"Albert Heijn","Boodschappen","",""\n'
    '"NL91RABO0123456789","EUR","RABONL2U","2","2026-05-01","2026-05-01","+2.500,00","1000,00","",'
    '"Werkgever BV","Salaris","april",""\n'
)


def test_ing_debit_credit_dates_and_counter_account():
    iban, rows = ing.parse(ING_CSV.encode())
    assert iban == "NL91INGB0001234567"
    assert [(r.date, r.amount, r.counterparty) for r in rows] == [
        (date(2026, 5, 3), Decimal("-12.34"), "Albert Heijn 1234"),        # "Af" = uitgave
        (date(2026, 5, 1), Decimal("2500.00"), "Werkgever BV"),            # "Bij" = inkomst, 2.500,00
    ]
    assert rows[1].counterparty_iban == "NL02ABNA0123456789" and rows[0].counterparty_iban is None
    assert rows[1].description == "Salaris april"


def test_ing_accepts_latin1_and_tab_separated_exports():
    latin1 = ING_CSV.replace("Overschrijving", "Overschrijving").replace("Werkgever BV", "Café Müller").encode("latin-1")
    assert ing.parse(latin1)[1][1].counterparty == "Café Müller"
    tabbed = ING_CSV.replace(";", "\t").encode()
    assert len(ing.parse(tabbed)[1]) == 2


def test_rabobank_signed_amounts_balance_and_descriptions():
    iban, rows = rabobank.parse(RABO_CSV.encode())
    assert iban == "NL91RABO0123456789"
    assert [(r.date, r.amount, r.balance_after) for r in rows] == [
        (date(2026, 5, 3), Decimal("-12.34"), Decimal("987.66")),
        (date(2026, 5, 1), Decimal("2500.00"), Decimal("1000.00")),         # "+2.500,00"
    ]
    assert rows[0].counterparty == "Albert Heijn" and rows[0].counterparty_iban == "NL02ABNA0123456789"
    assert rows[1].description == "Salaris april"                           # Omschrijving-1 en -2 samengevoegd


def test_unusable_files_raise_parse_errors_not_crashes():
    for parser in (ing, rabobank):
        with pytest.raises(ParseError):
            parser.parse(b"dit is geen csv\nmet twee regels")
