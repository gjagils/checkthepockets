"""Tests for CSV parsers."""

from decimal import Decimal
from datetime import date

from app.parsers import abn_amro, bunq, ics
from app.parsers.base import ParseError

import pytest


# === ABN AMRO ===


def test_abn_amro_basic():
    content = (
        "NL01ABNA0123456789\tEUR\t20240315\t20240315\t1000,00\t950,50\t-49,50\t"
        "/TRTP/SEPA Overboeking/IBAN/NL02RABO9876543210/NAME/Albert Heijn/REMI/Boodschappen\n"
    )
    iban, txs = abn_amro.parse(content.encode("latin-1"))
    assert iban == "NL01ABNA0123456789"
    assert len(txs) == 1
    assert txs[0].date == date(2024, 3, 15)
    assert txs[0].amount == Decimal("-49.50")
    assert txs[0].counterparty == "Albert Heijn"
    assert txs[0].counterparty_iban == "NL02RABO9876543210"
    assert txs[0].balance_after == Decimal("950.50")


def test_abn_amro_multiple():
    lines = (
        "NL01ABNA0123456789\tEUR\t20240315\t20240315\t1000,00\t950,50\t-49,50\tBoodschappen\n"
        "NL01ABNA0123456789\tEUR\t20240316\t20240316\t950,50\t1450,50\t500,00\tSalaris\n"
    )
    iban, txs = abn_amro.parse(lines.encode("utf-8"))
    assert len(txs) == 2
    assert txs[1].amount == Decimal("500.00")


def test_abn_amro_empty():
    iban, txs = abn_amro.parse(b"")
    assert txs == []


def test_abn_amro_too_few_columns():
    with pytest.raises(ParseError):
        abn_amro.parse(b"col1\tcol2\tcol3\n")


# === Bunq ===


def test_bunq_basic():
    content = (
        '"Date";"Amount";"Account";"Counterparty";"Name";"Description"\n'
        '"2024-03-15";"-25.50";"NL01BUNQ1234567890";"NL02RABO9876543210";"Albert Heijn";"Boodschappen"\n'
    )
    iban, txs = bunq.parse(content.encode("utf-8"))
    assert iban == "NL01BUNQ1234567890"
    assert len(txs) == 1
    assert txs[0].date == date(2024, 3, 15)
    assert txs[0].amount == Decimal("-25.50")
    assert txs[0].counterparty == "Albert Heijn"
    assert txs[0].description == "Boodschappen"


def test_bunq_comma_delimited():
    content = (
        "Date,Amount,Account,Counterparty,Name,Description\n"
        "2024-03-15,-25.50,NL01BUNQ1234567890,NL02RABO9876543210,Albert Heijn,Boodschappen\n"
    )
    iban, txs = bunq.parse(content.encode("utf-8"))
    assert len(txs) == 1
    assert txs[0].amount == Decimal("-25.50")


def test_bunq_empty():
    with pytest.raises(ParseError, match="Leeg bestand"):
        bunq.parse(b"")


def test_bunq_missing_headers():
    content = "Foo;Bar;Baz\n1;2;3\n"
    with pytest.raises(ParseError, match="Ontbrekende kolommen"):
        bunq.parse(content.encode("utf-8"))


# === ICS ===


def test_ics_basic():
    content = (
        "Datum,Omschrijving,Valuta,Bedrag\n"
        '15-03-2024,"ALBERT HEIJN 1234",EUR,"-25,50"\n'
    )
    iban, txs = ics.parse(content.encode("utf-8"))
    assert iban is None  # ICS has no IBAN
    assert len(txs) == 1
    assert txs[0].date == date(2024, 3, 15)
    assert txs[0].amount == Decimal("-25.50")
    assert txs[0].description == "ALBERT HEIJN 1234"


def test_ics_with_header_lines():
    content = (
        "ICS Creditcard Overzicht\n"
        "Kaartnummer: **** **** **** 1234\n"
        "\n"
        "Datum,Omschrijving,Valuta,Bedrag\n"
        '15-03-2024,"ALBERT HEIJN 1234",EUR,"-25,50"\n'
    )
    iban, txs = ics.parse(content.encode("latin-1"))
    assert len(txs) == 1
    assert txs[0].amount == Decimal("-25.50")


def test_ics_semicolon():
    content = (
        "Datum;Omschrijving;Valuta;Bedrag\n"
        '15-03-2024;"ALBERT HEIJN 1234";EUR;"-25,50"\n'
    )
    iban, txs = ics.parse(content.encode("utf-8"))
    assert len(txs) == 1


def test_ics_empty():
    with pytest.raises(ParseError):
        ics.parse(b"")


# === Import hash ===


def test_import_hash_unique():
    content1 = (
        "Date,Amount,Account,Counterparty,Name,Description\n"
        "2024-03-15,-25.50,NL01BUNQ1234567890,,Albert Heijn,Boodschappen\n"
    )
    content2 = (
        "Date,Amount,Account,Counterparty,Name,Description\n"
        "2024-03-15,-30.00,NL01BUNQ1234567890,,Albert Heijn,Boodschappen\n"
    )
    _, txs1 = bunq.parse(content1.encode())
    _, txs2 = bunq.parse(content2.encode())
    assert txs1[0].import_hash != txs2[0].import_hash


def test_import_hash_stable():
    content = (
        "Date,Amount,Account,Counterparty,Name,Description\n"
        "2024-03-15,-25.50,NL01BUNQ1234567890,,Albert Heijn,Boodschappen\n"
    )
    _, txs1 = bunq.parse(content.encode())
    _, txs2 = bunq.parse(content.encode())
    assert txs1[0].import_hash == txs2[0].import_hash
