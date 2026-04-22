"""AI-vision-OCR voor hypotheek-rente-tabellen.

Accepteert raw image-bytes en geeft tab-gescheiden tekst terug in het formaat dat
`app.mortgage_rate_parser.parse_bulk_rates` verwacht (rentevast-label + NHG +
≤65%/≤85%/≤90%/>90%-kolommen). De downstream-parser doet vervolgens exact
hetzelfde werk als bij de paste-flow — dit module vervangt slechts "tekst in
clipboard" door "tekst uit screenshot".
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Optional

from app.config import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)

OCR_MODEL = "claude-haiku-4-5-20251001"

ALLOWED_MEDIA_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

OCR_SYSTEM_PROMPT = """Je krijgt een screenshot van een Nederlandse hypotheek-rentetabel (meestal van ABN AMRO, maar andere banken ook).

Je TAAK: geef de tabel terug als **tab-gescheiden tekst** die direct door onze bulk-parser geconsumeerd kan worden.

FORMAT (strikt):
- EERSTE REGEL is een header. Begin met een TAB (lege eerste cel), dan exact:
  `\tNHG\t≤65%\t≤85%\t≤90%\t>90%`
- Daarna één datarij per rentevast-bucket: eerste kolom is het label (bv. "Variabel", "1 jaar vast", "10 jaar vast", "30 jaar vast"), daarna vijf numerieke kolommen in exact de volgorde NHG, ≤65%, ≤85%, ≤90%, >90%.
- Scheidings­teken: TAB (`\\t`), niet spaties of komma's.
- Percentages inclusief komma en procent-teken (bv. `3,75%`).
- Eén rij per regel, geen extra lege regels.

REGELS:
- Geef UITSLUITEND de header + tabelrijen terug. Geen uitleg, geen markdown, geen code-fences.
- Bij "Variabel"-rij: neem 'm gewoon over; onze parser slaat 'm zelf over.
- Als een cel leeg is in de afbeelding: gebruik het streepje `-` zodat de parser hem overslaat.
- Als je onzeker bent over een getal, neem je beste gok — we vallen terug op parser-errors die de gebruiker kan repareren.

Antwoord direct met de header + rijen, niets anders."""


@dataclass
class OCRResult:
    """Resultaat van een OCR-poging op een rente-screenshot."""

    ok: bool
    text: str = ""
    error: Optional[str] = None


def _encode_image(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def extract_rate_text(image_bytes: bytes, media_type: str) -> OCRResult:
    """Roep Claude Haiku 4.5 aan met de screenshot en retourneer tab-tekst.

    Geeft `OCRResult(ok=False, error=...)` bij problemen (geen API-key,
    afbeelding te groot, ongeldig media type, API-fout, leeg antwoord).
    """
    if media_type.lower() not in ALLOWED_MEDIA_TYPES:
        return OCRResult(
            ok=False,
            error=f"Alleen PNG, JPEG of WebP-afbeeldingen zijn toegestaan (kreeg: {media_type}).",
        )

    if len(image_bytes) > MAX_IMAGE_BYTES:
        return OCRResult(
            ok=False,
            error=f"Afbeelding is groter dan 5 MB ({len(image_bytes) / 1024 / 1024:.1f} MB).",
        )

    if not image_bytes:
        return OCRResult(ok=False, error="Lege afbeelding ontvangen.")

    if not ANTHROPIC_API_KEY:
        return OCRResult(ok=False, error="AI-OCR is niet geconfigureerd (geen API-key).")

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=OCR_MODEL,
            max_tokens=1500,
            system=[
                {
                    "type": "text",
                    "text": OCR_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type.lower().replace("image/jpg", "image/jpeg"),
                                "data": _encode_image(image_bytes),
                            },
                        },
                        {
                            "type": "text",
                            "text": "Hier is de rentetabel. Geef de tab-gescheiden rijen terug.",
                        },
                    ],
                }
            ],
        )
    except Exception as exc:  # pragma: no cover — API-fouten zijn lastig te simuleren
        log.warning("Rate-OCR call failed: %s", exc)
        return OCRResult(ok=False, error=f"AI-API fout: {exc}")

    try:
        text = resp.content[0].text.strip() if resp.content else ""
    except Exception:  # pragma: no cover
        log.warning("Rate-OCR response shape unexpected: %r", resp)
        return OCRResult(ok=False, error="Onverwacht antwoord van het model.")

    # Verwijder eventuele markdown fencing voor de zekerheid
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    if not text:
        return OCRResult(
            ok=False,
            error="Kon geen rente-tabel herkennen in de afbeelding. "
            "Probeer de paste-flow, of stuur een scherpere screenshot.",
        )

    return OCRResult(ok=True, text=text)
