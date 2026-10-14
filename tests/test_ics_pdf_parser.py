"""De ICS-PDF-parser tegen een echt PDF-bestand: vangt regressies in pdfplumber/pdfminer bij upgrades (ACT-40)."""
from decimal import Decimal

from app.parsers.ics_pdf import parse_ics_pdf

LINES = [
    "Afschrift 22 januari 2026",
    "21 dec.    22 dec.    PLUGSURFING          BERLIN         DEU                  16,10    Af",
    "01 jan.    02 jan.    OPENAI *CHATGPT SUBSCR  SAN FRANCISCO  USA  24,20 USD  21,06    Af",
    "Wisselkoers USD 1,149100",
    "GEINCASSEERD VORIG SALDO 100,00 Bij",
    "05 jan.    06 jan.    TERUGBETALING WEBSHOP     AMSTERDAM    NLD      10,00    Bij",
]


def _minimal_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with the given text lines (standard Helvetica, no libraries)."""
    def esc(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream = "BT /F1 9 Tf 30 800 Td 14 TL\n" + "\n".join(f"({esc(line)}) Tj T*" for line in lines) + "\nET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_parses_a_real_pdf_statement():
    transactions = parse_ics_pdf(_minimal_pdf(LINES))
    summary = [(t.description.split()[0], t.amount_eur, t.is_debit, t.transaction_date.isoformat()) for t in transactions]
    assert summary == [
        ("PLUGSURFING", Decimal("16.10"), True, "2025-12-21"),     # december op een januari-afschrift: vorig jaar
        ("OPENAI", Decimal("21.06"), True, "2026-01-01"),
        ("TERUGBETALING", Decimal("10.00"), False, "2026-01-05"),
    ]
