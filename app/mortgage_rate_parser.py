"""Parser voor bulk-invoer van hypotheekrentes (GJA-31).

Accepteert twee formaten:

1. **Simpel 3-kolom** (tab/komma/semicolon-separated): `fixed_years, ltv_max_pct,
   interest_rate`. Waardes zoals `10`, `0.85`, `3.75` of `3,75%` worden allemaal
   begrepen. Header-regel is optioneel.

2. **ABN-tabel** (paste uit browser): eerste kolom is rentevast-label
   (bv. "10 jaar vast"), vervolgkolommen bevatten percentages per LTV-bucket:
   `NHG`, `≤65%`, `≤85%`, `≤90%`, `>90%`. `NHG` en `Variabel` worden
   overgeslagen. LTV-bucket `>90%` wordt gemapt op `1.00`.

Het resultaat is een gestructureerde lijst met rijen waarvan elke entry
`fixed_years`, `ltv_max_pct` en `interest_rate` bevat als `Decimal`. Ongeldige
regels komen terug als `errors` zodat de caller een nette preview kan tonen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Iterable


@dataclass
class ParsedRate:
    fixed_years: int
    ltv_max_pct: Decimal   # fractie (0.85 = 85%)
    interest_rate: Decimal  # fractie (0.0375 = 3,75%)


@dataclass
class ParseResult:
    rows: list[ParsedRate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


_FIXED_YEARS_RE = re.compile(r"(\d+)\s*jaar", re.IGNORECASE)


def _to_decimal(raw: str) -> Decimal | None:
    """Parse '3,75%', '3.75', '0,0375', '85%', '0.85' → Decimal of None."""
    if raw is None:
        return None
    cleaned = raw.strip().replace("%", "").replace(",", ".").strip()
    if not cleaned or cleaned == "-":
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _as_fraction(value: Decimal, kind: str) -> Decimal | None:
    """Waarde normaliseren naar een fractie tussen 0 en 1.

    kind: 'rate' of 'ltv'. Interpretatie: 3.75 → 0.0375, 0.0375 blijft 0.0375.
    Voor LTV: 85 → 0.85, 0.85 blijft 0.85. Extreme waardes (>10 voor rate,
    >100 voor ltv) worden afgewezen.
    """
    if value is None:
        return None
    if value < 0:
        return None
    if kind == "rate":
        if value > 10:
            return None
        if value > 1:  # "3.75" → 0.0375
            return (value / Decimal(100)).quantize(Decimal("0.0001"))
        return value.quantize(Decimal("0.0001"))
    if kind == "ltv":
        if value > 100:
            return None
        if value > 1:  # "85" → 0.85
            return (value / Decimal(100)).quantize(Decimal("0.0001"))
        return value.quantize(Decimal("0.0001"))
    return None


def _split_line_cells(line: str) -> list[str]:
    """Split op tab, meerdere spaties, ; of , — eerst tab/; geprobeerd."""
    for sep in ("\t", ";"):
        if sep in line:
            return [c.strip() for c in line.split(sep)]
    if "," in line and re.search(r",\s", line):
        # Alleen als er komma's tussen cellen staan (gevolgd door spatie),
        # anders is de komma een decimaal-separator.
        return [c.strip() for c in line.split(",")]
    # Fallback: meerdere whitespace-sequenties → kolommen.
    parts = re.split(r"\s{2,}|\s+\|\s+", line.strip())
    return [p.strip() for p in parts if p.strip()]


def _extract_years(cell: str) -> int | None:
    cell = cell.strip().lower()
    if "variabel" in cell:
        return None
    m = _FIXED_YEARS_RE.search(cell)
    if m:
        return int(m.group(1))
    if cell.isdigit():
        return int(cell)
    return None


# LTV-header tokens → bovenlimiet als fractie.
# Volgorde is significant: meer-specifieke tokens (">90", "100%") staan boven
# het generieke "90%", anders matcht ">90%" met "90%" en botst met "≤90%".
_LTV_HEADER_MAP = [
    ("nhg", None),          # overslaan
    (">90", Decimal("1.00")),
    ("100%", Decimal("1.00")),
    ("≤65", Decimal("0.65")),
    ("<=65", Decimal("0.65")),
    ("65%", Decimal("0.65")),
    ("≤85", Decimal("0.85")),
    ("<=85", Decimal("0.85")),
    ("85%", Decimal("0.85")),
    ("≤90", Decimal("0.90")),
    ("<=90", Decimal("0.90")),
    ("90%", Decimal("0.90")),
]


def _ltv_from_header(cell: str) -> tuple[Decimal | None, bool]:
    """Returneert (ltv_fraction, is_nhg_skip)."""
    key = cell.strip().lower().replace(" ", "")
    if "nhg" in key:
        return None, True
    if "variabel" in key:
        return None, True
    for token, value in _LTV_HEADER_MAP:
        if token in key:
            if value is None:
                return None, True
            return value, False
    return None, False


# ──────────────────────────────────────────────────────────────────────────────
# Parsers
# ──────────────────────────────────────────────────────────────────────────────


def parse_bulk_rates(text: str) -> ParseResult:
    """Detecteer het formaat en parse. Leeg text → ParseResult zonder rijen."""
    if not text or not text.strip():
        return ParseResult(errors=["Geen invoer ontvangen."])

    lines = [ln for ln in (ln.rstrip() for ln in text.splitlines()) if ln.strip()]
    if not lines:
        return ParseResult(errors=["Geen bruikbare regels gevonden."])

    # Heuristiek: als de eerste kolom van de eerste regel een LTV-bucket of
    # 'NHG' bevat → ABN-tabel. Anders simpel 3-kolom.
    first_cells = _split_line_cells(lines[0])
    is_abn = any(
        _ltv_from_header(c)[0] is not None or "nhg" in c.lower()
        for c in first_cells[1:]
    )
    if is_abn:
        return _parse_abn_table(lines)
    return _parse_simple(lines)


def _parse_simple(lines: list[str]) -> ParseResult:
    """Parse simpel 3-kolom: fixed_years, ltv_max_pct, interest_rate."""
    result = ParseResult()
    # Detecteer header-regel: eerste cel moet niet-numeriek zijn.
    cells = _split_line_cells(lines[0])
    start = 0
    if cells and not cells[0].lstrip("-").replace(".", "", 1).isdigit():
        start = 1

    for line_no, line in enumerate(lines[start:], start=start + 1):
        cells = _split_line_cells(line)
        if len(cells) < 3:
            result.errors.append(f"Regel {line_no}: minder dan 3 kolommen ({line!r}).")
            continue
        try:
            fy = int(cells[0])
        except (TypeError, ValueError):
            result.errors.append(f"Regel {line_no}: ongeldige rentevast-waarde {cells[0]!r}.")
            continue
        if fy <= 0 or fy > 40:
            result.errors.append(f"Regel {line_no}: rentevast {fy} buiten bereik (1-40).")
            continue

        ltv_raw = _to_decimal(cells[1])
        rate_raw = _to_decimal(cells[2])
        ltv = _as_fraction(ltv_raw, "ltv")
        rate = _as_fraction(rate_raw, "rate")
        if ltv is None or ltv == 0:
            result.errors.append(f"Regel {line_no}: ongeldige LTV {cells[1]!r}.")
            continue
        if rate is None or rate == 0:
            result.errors.append(f"Regel {line_no}: ongeldige rente {cells[2]!r}.")
            continue
        result.rows.append(ParsedRate(fixed_years=fy, ltv_max_pct=ltv, interest_rate=rate))

    _flag_duplicates(result)
    return result


def _parse_abn_table(lines: list[str]) -> ParseResult:
    """Parse ABN-achtige tabel: kolom 0 = rentevast-label, kolom 1..N = LTV-buckets."""
    result = ParseResult()
    header_cells = _split_line_cells(lines[0])
    if len(header_cells) < 2:
        return ParseResult(errors=["ABN-tabel heeft te weinig kolommen."])

    # Map kolom-index → LTV-fractie (None = overslaan).
    col_ltv: list[Decimal | None] = [None]  # kolom 0 is rentevast-label
    for c in header_cells[1:]:
        ltv, is_skip = _ltv_from_header(c)
        if is_skip:
            col_ltv.append(None)
            result.skipped.append(f"Kolom {c!r} overgeslagen (NHG/Variabel).")
        else:
            col_ltv.append(ltv)

    for line_no, line in enumerate(lines[1:], start=2):
        cells = _split_line_cells(line)
        if not cells:
            continue
        fy = _extract_years(cells[0])
        if fy is None:
            result.skipped.append(f"Regel {line_no}: {cells[0]!r} (geen rentevast-periode).")
            continue
        for idx, cell in enumerate(cells[1:], start=1):
            if idx >= len(col_ltv):
                break
            ltv = col_ltv[idx]
            if ltv is None:
                continue  # overgeslagen kolom
            rate_raw = _to_decimal(cell)
            rate = _as_fraction(rate_raw, "rate")
            if rate is None or rate == 0:
                if cell.strip() and cell.strip() != "-":
                    result.errors.append(
                        f"Regel {line_no}, kolom {idx}: ongeldige rente {cell!r}.",
                    )
                continue
            result.rows.append(
                ParsedRate(fixed_years=fy, ltv_max_pct=ltv, interest_rate=rate),
            )

    _flag_duplicates(result)
    return result


def _flag_duplicates(result: ParseResult) -> None:
    """Markeer dubbele (fixed_years, ltv_max_pct)-combinaties als error."""
    seen: dict[tuple[int, Decimal], int] = {}
    for i, row in enumerate(result.rows):
        key = (row.fixed_years, row.ltv_max_pct)
        if key in seen:
            result.errors.append(
                f"Dubbele combinatie {row.fixed_years}j × LTV {row.ltv_max_pct*100:.0f}% in invoer.",
            )
        else:
            seen[key] = i


def compare_with_existing(
    parsed_rows: Iterable[ParsedRate],
    existing,  # iterable MortgageRateTable
) -> tuple[list[ParsedRate], list[tuple[ParsedRate, Decimal]]]:
    """Split parsed-rows op: (nieuw, overschrijf-met-oude-waarde)."""
    existing_map = {
        (e.fixed_years, Decimal(str(e.ltv_max_pct))): Decimal(str(e.interest_rate))
        for e in existing
    }
    new_rows: list[ParsedRate] = []
    updates: list[tuple[ParsedRate, Decimal]] = []
    for row in parsed_rows:
        key = (row.fixed_years, row.ltv_max_pct)
        if key in existing_map:
            updates.append((row, existing_map[key]))
        else:
            new_rows.append(row)
    return new_rows, updates
